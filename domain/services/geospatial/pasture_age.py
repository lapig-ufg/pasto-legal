import time
import traceback

from typing import Dict

import ee
import numpy as np
import PIL.Image
import xarray as xr

from semente.logging import log_error, log_info

from domain.services.geospatial import raster_layers, raster_render
from domain.services.geospatial.gee import _FEATURE_BUFFER, _IMAGE_DIMENSION
from domain.services.geospatial.pasture_cache import (
    dataset_exists,
    load_dataset,
    save_cache,
)
from domain.services.geospatial.pasture_classification import (
    _MAPBIOMAS_ASSET,
    _PASTURE_CLASS,
    _classify,
    _latest_mapbiomas_year,
)
from domain.services.geospatial.xee_grid import (
    _native_crs,
    _utm_grid,
    grid_for_roi,
    resample_nearest,
    source_grid_from_dataset,
)


_MAPBIOMAS_AGE_ASSET = "projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_age_v2"

_SCALE = 10

# Bump sempre que a lógica de cálculo mudar — invalida cache antigo incompatível
# com o novo formato/semântica em vez de servir resultado stale.
_CACHE_VERSION = "v2"

# 30-40 = idade calculada com precisão nesse intervalo. ≥40 = pixel bateu no teto
# do encoding do asset (sentinela "já madura ao início da série", idade real
# desconhecida e possivelmente bem maior que 40) OU chegou em 40 pelo próprio +1
# ano projetado — depois do .min(40) as duas situações ficam indistinguíveis, e
# ambas significam a mesma coisa na prática: "pelo menos ~40 anos, sem precisão
# além disso". Não misturamos isso com a faixa 30-40 medida com precisão.
_AGE_DICT = {1: "1-10", 2: "10-20", 3: "20-30", 4: "30-40", 5: "≥40 (idade real indeterminada)"}

_AGE_PALETTE = ["#ffffcc", "#a1dab4", "#41b6c4", "#2c7fb8", "#253494"]


def _age_years_image(roi: ee.Geometry, year: int) -> ee.Image:
    """
    Idade da pastagem (anos), decodificada da banda `year` do asset MapBiomas.

    Mesmo decode usado em `gee.py::get_pasture_age` (offset de 200 + sentinela
    -100 = pastagem já madura, tratada como 40 anos), mas SEM o bucketing final
    em classes — mantemos o valor contínuo para poder somar +1 ano depois.
    """
    age_asset = ee.Image(_MAPBIOMAS_AGE_ASSET).select(year - 2000)
    age = age_asset.subtract(200)
    age = age.where(age.eq(-100), 40)
    return age.clip(roi).rename("idade_anos")


def _area_by_age_class(age_years: "xr.DataArray") -> Dict[str, float]:
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
            result[_AGE_DICT[class_id]] = round(count * pixel_area_ha, 4)
    return result


def _bucket_age_class(age_years: ee.Image) -> ee.Image:
    """Classe 1-5 (mesmos limites de `_AGE_DICT`) a partir da idade contínua, para visualização."""
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


def estimate_pasture_age_on_the_fly(roi: ee.Geometry, car_code: str, pred_year: int = None, train_year: int = None) -> Dict:
    """
    Idade da pastagem on-the-fly: idade do MapBiomas no ano de treino + 1 ano nas
    áreas que continuam pastagem na classificação on-the-fly do ano seguinte;
    pastagem nova (não era pastagem no ano de treino) começa com 1 ano.

    Estratégia igual às demais camadas on-the-fly: toda a combinação (downsample
    implícito do asset 30m para a grade de 10m, soma de +1 ano, máscaras) roda no
    GEE server-side numa única banda; Xee só baixa o resultado final e persiste em
    zarr — cache local (`tmp/`) ou S3 conforme `config.APP_ENV`.

    Args:
        roi (ee.Geometry): Geometria do imóvel (MultiPolygon).
        car_code (str): Código(s) CAR do imóvel — usado como chave de cache.
        pred_year (int, optional): Ano alvo da idade. Default: train_year + 1.
        train_year (int, optional): Ano-base do MapBiomas. Default: ano mais recente disponível.

    Returns:
        Dict: {"area_by_age_class_ha", "pred_year", "train_year", "cached", "imagem"}
    """
    try:
        train_year = train_year or _latest_mapbiomas_year()
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
            return {
                "imagem": image,
                "area_by_age_class_ha": area_by_class,
                "pred_year": pred_year,
                "train_year": train_year,
                "cached": True,
            }

        start = time.perf_counter()

        classified, embedding_check = _classify(roi=roi, train_year=train_year, pred_year=pred_year)

        was_pasture_train = (
            ee.Image(_MAPBIOMAS_ASSET).select(f"classification_{train_year}").eq(_PASTURE_CLASS)
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

        log_info(f"[{car_code}] estimate_pasture_age_on_the_fly {pred_year}: {time.perf_counter() - start:.2f}s")

        return {
            "imagem": image,
            "area_by_age_class_ha": area_by_class,
            "pred_year": pred_year,
            "train_year": train_year,
            "cached": False,
        }

    except ValueError as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] {error}")
    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Falha no Earth Engine ao estimar idade da pastagem: {error}")
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Erro inesperado ao estimar idade da pastagem: {error}")