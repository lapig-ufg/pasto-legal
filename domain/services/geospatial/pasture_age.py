import time
import traceback

from dataclasses import dataclass
from typing import Literal, Optional

import ee
import numpy as np
import PIL.Image
import xarray as xr

from semente.logging import log_error, log_info, log_warning

from domain.schemas.property_stats import AgeData, AgeStats, Value
from domain.services.geospatial import raster_layers, raster_render
from domain.services.geospatial.gee import _FEATURE_BUFFER, _IMAGE_DIMENSION
from domain.services.geospatial.mapbiomas import (
    AGE_ASSET,
    AGE_ASSET_BASE_YEAR,
    AGE_CLASSES,
    PASTURE_CLASS,
    CLASSIFICATION_ASSET,
    latest_asset_year,
    latest_classification_year,
)
from domain.services.geospatial.pasture_cache import (
    dataset_exists,
    load_dataset,
    save_cache,
)
from domain.services.geospatial.pasture_classification import _classify_cached
from domain.services.geospatial.xee_grid import (
    _native_crs,
    _utm_grid,
    grid_for_roi,
    resample_nearest,
    source_grid_from_dataset,
)


_SCALE = 10

# Bump sempre que a lógica de cálculo mudar — invalida cache antigo incompatível
# com o novo formato/semântica em vez de servir resultado stale.
_CACHE_VERSION = "v3"

_AGE_PALETTE = ["#ffffcc", "#a1dab4", "#41b6c4", "#2c7fb8", "#253494"]


def _age_years_image(roi: ee.Geometry, year: int) -> ee.Image:
    """
    Idade da pastagem (anos), decodificada da banda `year` do asset MapBiomas.

    Mesmo decode usado em `get_pasture_age` (offset de 200 + sentinela -100 =
    pastagem já madura, tratada como 40 anos), mas SEM o bucketing final em
    classes — mantemos o valor contínuo para poder somar +1 ano depois.
    """
    age_asset = ee.Image(AGE_ASSET).select(year - AGE_ASSET_BASE_YEAR)
    age = age_asset.subtract(200)
    age = age.where(age.eq(-100), 40)
    return age.clip(roi).rename("idade_anos")


def _area_by_age_class(age_years: "xr.DataArray") -> dict[str, float]:
    values = age_years.values
    valid = values[~np.isnan(values)]
    if valid.size == 0:
        return {}

    # right=True (bins[i-1] < x <= bins[i]) pra bater exatamente com os limites usados
    # em _bucket_age_class (.gt(30).And(.lt(40)) -> 4, .gte(40) -> 5): x=30 cai na
    # classe 3, só (30,40) cai na 4, >=40 (teto do encoding) vira a 5 "indeterminada".
    classes = np.digitize(valid, [0, 10, 20, 30, 40 - 1e-9, float("inf")], right=True)
    pixel_area_ha = (_SCALE ** 2) / 1e4

    result = {}
    for class_id in (1, 2, 3, 4, 5):
        count = int((classes == class_id).sum())
        if count:
            result[AGE_CLASSES[class_id]] = round(count * pixel_area_ha, 4)
    return result


def _bucket_age_class(age_years: ee.Image) -> ee.Image:
    """Classe 1-5 (mesmos limites de `AGE_CLASSES`) a partir da idade contínua, para visualização."""
    return (
        age_years.where(age_years.gte(1).And(age_years.lte(10)), 1)
        .where(age_years.gt(10).And(age_years.lte(20)), 2)
        .where(age_years.gt(20).And(age_years.lte(30)), 3)
        .where(age_years.gt(30).And(age_years.lt(40)), 4)
        .where(age_years.gte(40), 5)
    )


def _bucket_age_values(values: np.ndarray) -> np.ndarray:
    """Buckets continuous age values into classes 1..5 (0 = no data)."""
    result = np.zeros(values.shape, dtype=np.int16)
    valid = np.isfinite(values)
    result[valid & (values >= 1) & (values <= 10)] = 1
    result[valid & (values > 10) & (values <= 20)] = 2
    result[valid & (values > 20) & (values <= 30)] = 3
    result[valid & (values > 30) & (values < 40)] = 4
    result[valid & (values >= 40)] = 5
    return result


def _render_age_image(
    roi: ee.Geometry,
    age_years,
    source_grid,
    car_code: str,
    base_year: int,
    coords,
) -> "PIL.Image.Image":
    """Mapa de idade (5 classes) sobreposto ao satélite, renderizado localmente."""
    class_colors = {
        1: _AGE_PALETTE[0], 2: _AGE_PALETTE[1], 3: _AGE_PALETTE[2],
        4: _AGE_PALETTE[3], 5: _AGE_PALETTE[4],
    }
    class_labels = {
        1: "1-10", 2: "10-20", 3: "20-30", 4: "30-40",
        5: "≥40 (indeterminada)",
    }

    render_grid = grid_for_roi(roi, scale=_SCALE, buffer_m=_FEATURE_BUFFER)
    values = resample_nearest(age_years.values, source_grid, render_grid)
    classes = _bucket_age_values(values)

    base_rgb = raster_layers.get_base_raster(
        roi=roi, feature_key=car_code, year=base_year, grid=render_grid
    )
    return raster_render.render_discrete_map(
        base_rgb=base_rgb,
        values=classes,
        coords=coords,
        grid=render_grid,
        class_colors=class_colors,
        class_labels=class_labels,
        title="Idade da Pastagem (anos)",
        dimension=_IMAGE_DIMENSION,
    )


@dataclass
class AgeAnalysis:
    """Pasture age result, from either source."""

    stats: AgeStats
    image: Optional["PIL.Image.Image"]
    pred_year: int
    train_year: Optional[int]
    source: Literal["on_the_fly", "mapbiomas"]
    cached: bool = False


def _age_stats_from_areas(area_by_class: dict[str, float], observation_year: int) -> AgeStats:
    return AgeStats(
        observation_year=observation_year,
        data=[
            AgeData(age=age_range, amount=Value(value=area, unity="hectares (ha)"))
            for age_range, area in area_by_class.items()
        ],
    )


def get_pasture_age(roi: ee.Geometry, year: int, month: int = None) -> AgeStats:
    """
    Static pasture age (ha per age class) via MapBiomas Collection 10.

    Raw ages are reclassified into the same 5 classes used by the estimated
    layer (1-10, 10-20, 20-30, 30-40 and the censored ≥40 class).

    Args:
        roi (ee.Geometry): Region of interest (farm polygon).
        year (int): Reference year of the mapping.
        month (int, optional): Ignored; kept for signature compatibility.

    Returns:
        AgeStats: Observation year and areas per age range (ha).
    """
    target_year = max(
        AGE_ASSET_BASE_YEAR,
        min(year, latest_asset_year(AGE_ASSET, base_year=AGE_ASSET_BASE_YEAR)),
    )
    age_asset = ee.Image(AGE_ASSET)
    raw_age = age_asset.select(target_year - AGE_ASSET_BASE_YEAR).subtract(200)
    is_censored = raw_age.eq(-100)

    last_age = raw_age.where(is_censored, 40)
    last_age = (
        last_age.where(last_age.gte(1).And(last_age.lte(10)), 1)
        .where(last_age.gt(10).And(last_age.lte(20)), 2)
        .where(last_age.gt(20).And(last_age.lte(30)), 3)
        .where(last_age.gt(30).And(last_age.lte(40)), 4)
        .where(is_censored, 5)
    ).rename("Anos")

    area_img = ee.Image.pixelArea().divide(10000).addBands(last_age)
    stats = area_img.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName="class"),
        geometry=roi,
        scale=30,
        maxPixels=1e13,
    )

    groups_info = stats.get("groups").getInfo()
    age_data_list: list[AgeData] = []

    if groups_info:
        for group in groups_info:
            class_id = int(group["class"])
            class_name = AGE_CLASSES.get(class_id)
            if class_name is None:
                continue
            area_value = round(float(group["sum"]), 2)
            age_data_list.append(
                AgeData(age=class_name, amount=Value(value=area_value, unity="hectares (ha)"))
            )

    return AgeStats(observation_year=target_year, data=age_data_list)


def _render_static_age_image(
    roi: ee.Geometry, year: int, car_code: str
) -> "PIL.Image.Image":
    """Render the static MapBiomas age classes over the satellite base."""
    grid = grid_for_roi(roi, scale=_SCALE, buffer_m=_FEATURE_BUFFER)
    dataset = raster_layers.download_image_dataset(
        _age_years_image(roi, year), grid, band_name="idade_anos", dtype="float32"
    )
    source_grid = source_grid_from_dataset(dataset, "idade_anos")
    return _render_age_image(
        roi=roi,
        age_years=dataset["idade_anos"].isel(time=0),
        source_grid=source_grid,
        car_code=car_code,
        base_year=year,
        coords=roi.coordinates().getInfo(),
    )


def estimate_pasture_age(roi: ee.Geometry, car_code: str, pred_year: int = None, train_year: int = None) -> AgeAnalysis:
    """
    Estimated pasture age: MapBiomas age at the training year + 1 year on areas
    that remain pasture in the next year's classification; new pasture starts
    at 1 year. Keeps the continuous age so the +1 projection is possible.

    Args:
        roi (ee.Geometry): Geometria do imóvel (MultiPolygon).
        car_code (str): Código(s) CAR do imóvel — usado como chave de cache.
        pred_year (int, optional): Ano alvo da idade. Default: train_year + 1.
        train_year (int, optional): Ano-base do MapBiomas. Default: ano mais recente disponível.

    Returns:
        AgeAnalysis: stats, map image, reference years and cache status.
    """
    try:
        train_year = train_year or latest_classification_year()
        pred_year = pred_year or (train_year + 1)
        cache_key = f"{pred_year}_{_CACHE_VERSION}"

        if dataset_exists(car_code, cache_key, kind="age"):
            dataset = load_dataset(car_code, cache_key, kind="age")
            age_years = dataset["idade_anos"].isel(time=0)
            area_by_class = _area_by_age_class(age_years)
            source_grid = source_grid_from_dataset(dataset, "idade_anos")
            image = _render_age_image(
                roi=roi,
                age_years=age_years,
                source_grid=source_grid,
                car_code=car_code,
                base_year=pred_year,
                coords=roi.coordinates().getInfo(),
            )
            log_info(f"[{car_code}] pasture age cache hit ({pred_year})")
            return AgeAnalysis(
                stats=_age_stats_from_areas(area_by_class, pred_year),
                image=image,
                pred_year=pred_year,
                train_year=train_year,
                source="on_the_fly",
                cached=True,
            )

        start = time.perf_counter()

        classified, embedding_check = _classify_cached(
            roi=roi, car_code=car_code, train_year=train_year, pred_year=pred_year
        )

        was_pasture_train = (
            ee.Image(CLASSIFICATION_ASSET)
            .select(f"classification_{train_year}")
            .eq(PASTURE_CLASS)
        )
        age_train = _age_years_image(roi=roi, year=train_year)

        new_age = (
            age_train.add(1)
            .updateMask(was_pasture_train)
            .unmask(1)
            .updateMask(classified)
            .min(40)
            .max(1)
            .rename("idade_anos")
        )

        ts = ee.Date(f"{pred_year}-01-01").millis()
        collection = ee.ImageCollection([new_age.toFloat().set("system:time_start", ts)])
        crs = _native_crs(embedding_check)
        transform, width, height = _utm_grid(roi=roi, crs=crs, scale=_SCALE)

        dataset = xr.open_dataset(
            collection, engine="ee", crs=crs, crs_transform=transform, shape_2d=(width, height),
        ).load()

        age_years = dataset["idade_anos"].isel(time=0)
        area_by_class = _area_by_age_class(age_years)
        source_grid = source_grid_from_dataset(dataset, "idade_anos")

        image = _render_age_image(
            roi=roi,
            age_years=age_years,
            source_grid=source_grid,
            car_code=car_code,
            base_year=pred_year,
            coords=roi.coordinates().getInfo(),
        )
        save_cache(car_code, cache_key, dataset, image, kind="age")

        log_info(f"[{car_code}] estimate_pasture_age {pred_year}: {time.perf_counter() - start:.2f}s")

        return AgeAnalysis(
            stats=_age_stats_from_areas(area_by_class, pred_year),
            image=image,
            pred_year=pred_year,
            train_year=train_year,
            source="on_the_fly",
            cached=False,
        )

    except ValueError as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] {error}")
    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Falha no Earth Engine ao estimar idade da pastagem: {error}")
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Erro inesperado ao estimar idade da pastagem: {error}")


def analyze_pasture_age(roi: ee.Geometry, car_code: str, year: int = None) -> AgeAnalysis:
    """Resolve the best available pasture age (estimated → MapBiomas)."""
    try:
        return estimate_pasture_age(roi=roi, car_code=car_code, pred_year=year)
    except Exception as error:
        log_warning(
            f"[{car_code}] idade estimada indisponível ({error}); "
            "usando o mapeamento estático do MapBiomas"
        )
        latest_year = latest_asset_year(AGE_ASSET, base_year=AGE_ASSET_BASE_YEAR)
        target_year = max(
            AGE_ASSET_BASE_YEAR, min(year or latest_year, latest_year)
        )
        stats = get_pasture_age(roi=roi, year=target_year)
        try:
            image = _render_static_age_image(roi=roi, year=target_year, car_code=car_code)
        except Exception as image_error:
            log_warning(f"[{car_code}] mapa estático de idade indisponível: {image_error}")
            image = None
        return AgeAnalysis(
            stats=stats,
            image=image,
            pred_year=target_year,
            train_year=None,
            source="mapbiomas",
            cached=False,
        )