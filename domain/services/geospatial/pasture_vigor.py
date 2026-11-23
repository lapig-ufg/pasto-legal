import math
import time
import traceback

from dataclasses import dataclass
from typing import List, Literal, Optional, Tuple

import ee
import numpy as np
import PIL.Image
import xarray as xr

from semente.logging import log_error, log_info, log_warning

from domain.schemas.property_stats import Value, VigorData, VigorStats
from domain.services.geospatial import raster_layers, raster_render
from domain.services.geospatial.gee import _FEATURE_BUFFER, _IMAGE_DIMENSION
from domain.services.geospatial.mapbiomas import (
    CLASSIFICATION_ASSET,
    PASTURE_CLASS,
    VIGOR_ASSET,
    VIGOR_ASSET_BASE_YEAR,
    VIGOR_CLASSES,
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


_S2_ASSET = "COPERNICUS/S2_SR_HARMONIZED"

_CLOUD_SCORE_ASSET = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"

_CS_CDF_THRESHOLD = 0.60

_SCALE = 10

_MIN_PIXELS_PER_CLASS = 30

# Bump sempre que a lógica de cálculo/calibração mudar — invalida cache antigo
# incompatível com o novo formato/semântica em vez de servir resultado stale.
_CACHE_VERSION = "v2"

# Limiares fixos de amplitude (NDVI) usados só quando a calibração por propriedade
# não é confiável (poucos pixels por classe ou propriedade sem as 3 classes do
# MapBiomas presentes) — estimativa grosseira p/ pastagem no Cerrado, não substitui
# a metodologia oficial do MapBiomas.
_FALLBACK_AMPLITUDE_THRESHOLDS = [0.08, 0.18]

_VIGOR_PALETTE = ["#d7191c", "#fdae61", "#1a9641"]


def _vigor_metrics_image(roi: ee.Geometry, year: int) -> ee.Image:
    """
    Amplitude e média anual do NDVI via regressão harmônica (1 ciclo/ano) sobre
    Sentinel-2 + Cloud Score+, mesma técnica do tutorial de referência do Google
    (trend + 1 harmônico) linkado na issue — adaptada pra Sentinel-2/Cloud Score+
    em vez de Landsat/QA_PIXEL, consistente com o resto do pipeline a 10m.

    Retorna 2 bandas: "amplitude" (proxy de estacionalidade/vigor) e "mean_ndvi"
    (nível médio de verdor no ano).
    """
    independents = ee.List(["constant", "t", "cos", "sin"])
    dependent = "NDVI"

    def mask_s2(image):
        clear = image.select("cs_cdf").gte(_CS_CDF_THRESHOLD)
        optical = image.select("B.*").divide(10000)
        return image.addBands(optical, None, True).updateMask(clear)

    def add_variables(image):
        years = image.date().difference(ee.Date("1970-01-01"), "year")
        ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")
        return (
            image.addBands(ndvi)
            .addBands(ee.Image(years).rename("t"))
            .float()
            .addBands(ee.Image.constant(1).rename("constant"))
        )

    def add_harmonics(image):
        time_radians = image.select("t").multiply(2 * math.pi)
        return image.addBands(time_radians.cos().rename("cos")).addBands(time_radians.sin().rename("sin"))

    # Filtra ambas as coleções por espaço/tempo ANTES do linkCollection — juntar primeiro
    # (ordem antiga) obriga o GEE a casar contra o arquivo global inteiro das duas coleções
    # antes de descartar qualquer coisa, o que é desnecessariamente pesado e reduz margem
    # contra timeout em dias de servidor mais lento.
    date_range = (f"{year}-01-01", f"{year + 1}-01-01")
    s2_filtered = ee.ImageCollection(_S2_ASSET).filterBounds(roi).filterDate(*date_range)
    cloud_score_filtered = ee.ImageCollection(_CLOUD_SCORE_ASSET).filterBounds(roi).filterDate(*date_range)

    harmonic_collection = (
        s2_filtered
        .linkCollection(cloud_score_filtered, ["cs_cdf"])
        .map(mask_s2)
        .map(add_variables)
        .map(add_harmonics)
    )

    harmonic_trend = harmonic_collection.select(independents.add(dependent)).reduce(
        ee.Reducer.linearRegression(numX=independents.length(), numY=1)
    )
    coefficients = harmonic_trend.select("coefficients").arrayProject([0]).arrayFlatten([independents])

    amplitude = coefficients.select("cos").hypot(coefficients.select("sin")).rename("amplitude")
    mean_ndvi = harmonic_collection.select("NDVI").mean().rename("mean_ndvi")

    return amplitude.addBands(mean_ndvi).clip(roi)


def _calibrate_thresholds(
    static_class: np.ndarray, amplitude: np.ndarray, mean_ndvi: np.ndarray
) -> Tuple[List[float], List[int], str, str]:
    """
    Deriva 2 limiares que separam as 3 classes estáticas do MapBiomas (no ano de
    treino, dentro da própria propriedade) usando a métrica (amplitude ou
    mean_ndvi) com melhor separação entre classes.

    `order` é a peça que faz a classificação final não sair invertida: como as
    classes são ordenadas pelo VALOR da métrica (não pelo número da classe), a
    relação pode vir invertida numa propriedade específica (ex.: pasto irrigado
    com baixa amplitude e alto vigor) — sem devolver essa ordem, o chamador não
    tem como saber se "métrica baixa" corresponde à classe 1 (Baixo) ou à 3 (Alto).

    Returns:
        Tuple[List[float], List[int], str, str]: (2 limiares ordenados, as 3
        classes originais do MapBiomas ordenadas por valor crescente da métrica
        — ordered[0] é a classe do tercil mais baixo —, nome da métrica escolhida,
        "calibrated" ou "fallback").
    """
    valid = ~np.isnan(static_class)

    best_metric_name, best_thresholds, best_order, best_score = None, None, None, -math.inf

    for metric_name, metric in (("amplitude", amplitude), ("mean_ndvi", mean_ndvi)):
        medians, spreads, counts = {}, {}, {}
        for class_id in (1, 2, 3):
            mask = valid & (static_class == class_id) & ~np.isnan(metric)
            counts[class_id] = int(mask.sum())
            if counts[class_id] > 0:
                medians[class_id] = float(np.median(metric[mask]))
                spreads[class_id] = float(np.median(np.abs(metric[mask] - medians[class_id])))  # MAD

        if any(counts.get(c, 0) < _MIN_PIXELS_PER_CLASS for c in (1, 2, 3)):
            continue

        ordered = sorted(medians, key=medians.get)
        thresholds = [
            (medians[ordered[0]] + medians[ordered[1]]) / 2,
            (medians[ordered[1]] + medians[ordered[2]]) / 2,
        ]
        gap = min(medians[ordered[1]] - medians[ordered[0]], medians[ordered[2]] - medians[ordered[1]])
        pooled_spread = (spreads[ordered[0]] + spreads[ordered[1]] + spreads[ordered[2]]) / 3 + 1e-9
        score = gap / pooled_spread

        if score > best_score:
            best_metric_name, best_thresholds, best_order, best_score = metric_name, thresholds, ordered, score

    if best_metric_name is None:
        return list(_FALLBACK_AMPLITUDE_THRESHOLDS), [1, 2, 3], "amplitude", "fallback"

    return best_thresholds, best_order, best_metric_name, "calibrated"


def _area_by_vigor_class(vigor_class: np.ndarray) -> dict[str, float]:
    valid = vigor_class[~np.isnan(vigor_class)]
    pixel_area_ha = (_SCALE ** 2) / 1e4

    result = {}
    for class_id in (1, 2, 3):
        count = int((valid == class_id).sum())
        if count:
            result[VIGOR_CLASSES[class_id]] = round(count * pixel_area_ha, 4)
    return result


def _render_vigor_image(
    roi: ee.Geometry,
    vigor_class,
    source_grid,
    car_code: str,
    base_year: int,
    coords,
) -> "PIL.Image.Image":
    class_colors = {1: _VIGOR_PALETTE[0], 2: _VIGOR_PALETTE[1], 3: _VIGOR_PALETTE[2]}
    class_labels = {1: "Baixo", 2: "Médio", 3: "Alto"}

    render_grid = grid_for_roi(roi, scale=_SCALE, buffer_m=_FEATURE_BUFFER)
    values = resample_nearest(vigor_class, source_grid, render_grid)
    values = np.nan_to_num(values, nan=0).astype(int)

    base_rgb = raster_layers.get_base_raster(
        roi=roi, feature_key=car_code, year=base_year, grid=render_grid
    )
    return raster_render.render_discrete_map(
        base_rgb=base_rgb,
        values=values,
        coords=coords,
        grid=render_grid,
        class_colors=class_colors,
        class_labels=class_labels,
        title="Vigor da Pastagem (estimativa)",
        dimension=_IMAGE_DIMENSION,
    )


@dataclass
class VigorAnalysis:
    """Pasture vigor result, from either source."""

    stats: VigorStats
    image: Optional["PIL.Image.Image"]
    pred_year: int
    train_year: Optional[int]
    source: Literal["on_the_fly", "mapbiomas"]
    cached: bool = False
    calibration_metric: Optional[str] = None
    calibration_status: Optional[str] = None


def _vigor_stats_from_areas(area_by_class: dict[str, float], observation_year: int) -> VigorStats:
    return VigorStats(
        observation_year=observation_year,
        data=[
            VigorData(vigor=vigor_label, amount=Value(value=area, unity="hectares (ha)"))
            for vigor_label, area in area_by_class.items()
        ],
    )


def get_pasture_vigor(roi: ee.Geometry, year: int, month: int = None) -> VigorStats:
    """
    Static pasture vigor (ha per class) via MapBiomas Collection 10.

    Classes: 1 = Low (severe degradation, potentially biological),
    2 = Medium (moderate degradation), 3 = High (high vegetative vigor).

    Args:
        roi (ee.Geometry): Region of interest (farm polygon).
        year (int): Reference year of the mapping.
        month (int, optional): Ignored; kept for signature compatibility.

    Returns:
        VigorStats: Observation year and list of areas per vigor class (ha).
    """
    target_year = max(
        VIGOR_ASSET_BASE_YEAR,
        min(year, latest_asset_year(VIGOR_ASSET, base_year=VIGOR_ASSET_BASE_YEAR)),
    )
    vigor_asset = ee.Image(VIGOR_ASSET)
    last_vigor = vigor_asset.select(target_year - VIGOR_ASSET_BASE_YEAR)

    area_img = ee.Image.pixelArea().divide(10000).addBands(last_vigor)
    stats = area_img.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName="class"),
        geometry=roi,
        scale=30,
        maxPixels=1e13,
    )

    groups_info = stats.get("groups").getInfo()
    vigor_data_list: list[VigorData] = []

    if groups_info:
        for group in groups_info:
            class_id = int(group["class"])
            vigor_name = VIGOR_CLASSES.get(class_id)
            if vigor_name is None:
                continue
            area_value = round(float(group["sum"]), 2)
            vigor_data_list.append(
                VigorData(vigor=vigor_name, amount=Value(value=area_value, unity="hectares (ha)"))
            )

    return VigorStats(observation_year=target_year, data=vigor_data_list)


def retrieve_pasture_vigor_image(
    coords: List[List[List[List[float]]]],
    year: int = None,
    feature_key: Optional[str] = None,
) -> PIL.Image:
    """
    Static MapBiomas vigor map over the satellite base. Used as the fallback
    when the estimated vigor is unavailable.
    """
    try:
        class_colors = {1: "#d7191c", 2: "#fdae61", 3: "#1a9641"}
        class_labels = {1: "Baixo", 2: "Médio", 3: "Alto"}

        roi = ee.Geometry.MultiPolygon(coords)
        feature_key = feature_key or raster_layers.feature_key_from_coords(coords)
        grid = grid_for_roi(roi, scale=_SCALE, buffer_m=_FEATURE_BUFFER)

        latest_year = latest_asset_year(VIGOR_ASSET, base_year=VIGOR_ASSET_BASE_YEAR)
        target_year = max(
            VIGOR_ASSET_BASE_YEAR, min(year or latest_year, latest_year)
        )

        def _vigor_image() -> ee.Image:
            return (
                ee.Image(VIGOR_ASSET)
                .select(target_year - VIGOR_ASSET_BASE_YEAR)
                .rename("vigor_class")
            )

        key = raster_layers.layer_cache_key([target_year], grid, "v1")
        values, grid = raster_layers.get_layer_array(
            roi=roi,
            feature_key=feature_key,
            kind="vigor_static",
            key=key,
            image_factory=_vigor_image,
            band_name="vigor_class",
            grid=grid,
            scale=10,
        )

        values = np.nan_to_num(values, nan=0).astype(int)
        base_rgb = raster_layers.get_base_raster(
            roi=roi, feature_key=feature_key, year=target_year, grid=grid
        )
        return raster_render.render_discrete_map(
            base_rgb=base_rgb,
            values=values,
            coords=coords,
            grid=grid,
            class_colors=class_colors,
            class_labels=class_labels,
            title="Vigor da Pastagem",
            dimension=_IMAGE_DIMENSION,
        )

    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Falha ao processar as coordenadas no satélite. "
            f"Verifique se as coordenadas da área estão corretas. Detalhes: {str(error)}"
        )
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Ocorreu um erro inesperado ao gerar a imagem da fazenda. Detalhes: {str(error)}"
        )


def estimate_pasture_vigor(roi: ee.Geometry, car_code: str, pred_year: int = None, train_year: int = None) -> VigorAnalysis:
    """
    Estimated pasture vigor: harmonic regression over NDVI (Sentinel-2 +
    Cloud Score+), calibrated per property against the static MapBiomas vigor
    asset at the training year, then applied to the next year's pasture
    classification.

    IMPORTANT: this is our own heuristic, not MapBiomas' official methodology.
    When there are not enough pixels per class to calibrate, it falls back to
    fixed thresholds (`calibration_status == "fallback"`).

    Args:
        roi (ee.Geometry): Geometria do imóvel (MultiPolygon).
        car_code (str): Código(s) CAR do imóvel — usado como chave de cache.
        pred_year (int, optional): Ano alvo do vigor. Default: train_year + 1.
        train_year (int, optional): Ano-base (calibração). Default: ano mais recente disponível no MapBiomas.

    Returns:
        VigorAnalysis: stats, map image, reference years, cache status and
        calibration metadata.
    """
    try:
        train_year = train_year or latest_classification_year()
        pred_year = pred_year or (train_year + 1)
        cache_key = f"{pred_year}_{_CACHE_VERSION}"

        if dataset_exists(car_code, cache_key, kind="vigor"):
            dataset = load_dataset(car_code, cache_key, kind="vigor")
            vigor_class = dataset["vigor_class"].isel(time=0).values
            source_grid = source_grid_from_dataset(dataset, "vigor_class")
            image = _render_vigor_image(
                roi=roi,
                vigor_class=vigor_class,
                source_grid=source_grid,
                car_code=car_code,
                base_year=pred_year,
                coords=roi.coordinates().getInfo(),
            )
            log_info(f"[{car_code}] pasture vigor cache hit ({pred_year})")
            return VigorAnalysis(
                stats=_vigor_stats_from_areas(_area_by_vigor_class(vigor_class), pred_year),
                image=image,
                pred_year=pred_year,
                train_year=train_year,
                source="on_the_fly",
                cached=True,
                calibration_metric=dataset.attrs.get("calibration_metric"),
                calibration_status=dataset.attrs.get("calibration_status"),
            )

        start = time.perf_counter()

        classified, embedding_check = _classify_cached(
            roi=roi, car_code=car_code, train_year=train_year, pred_year=pred_year
        )
        crs = _native_crs(embedding_check)
        transform, width, height = _utm_grid(roi=roi, crs=crs, scale=_SCALE)

        was_pasture_train = (
            ee.Image(CLASSIFICATION_ASSET)
            .select(f"classification_{train_year}")
            .eq(PASTURE_CLASS)
        )
        static_vigor_train = (
            ee.Image(VIGOR_ASSET)
            .select(train_year - VIGOR_ASSET_BASE_YEAR)
            .rename("static_class")
        )
        metrics_train = _vigor_metrics_image(roi=roi, year=train_year)

        calibration_image = (
            static_vigor_train.addBands(metrics_train).updateMask(was_pasture_train).toFloat()
        )
        calibration_collection = ee.ImageCollection(
            [calibration_image.set("system:time_start", ee.Date(f"{train_year}-01-01").millis())]
        )
        calibration_dataset = xr.open_dataset(
            calibration_collection, engine="ee", crs=crs, crs_transform=transform, shape_2d=(width, height),
        ).load()

        thresholds, order, metric_name, calibration_status = _calibrate_thresholds(
            static_class=calibration_dataset["static_class"].isel(time=0).values,
            amplitude=calibration_dataset["amplitude"].isel(time=0).values,
            mean_ndvi=calibration_dataset["mean_ndvi"].isel(time=0).values,
        )
        if calibration_status == "fallback":
            log_warning(f"[{car_code}] vigor: calibração por propriedade indisponível, usando limiar fixo")

        metrics_pred = _vigor_metrics_image(roi=roi, year=pred_year).select(metric_name)
        # tercile 0/1/2 = "métrica baixa/média/alta" — remap() traduz isso de volta pra
        # classe real do MapBiomas usando `order` (pode não ser [1,2,3]: numa propriedade
        # onde a relação métrica<->vigor é invertida, ex. pasto irrigado com baixa
        # amplitude e alto vigor, sem esse remap a classificação sairia invertida).
        tercile = metrics_pred.gt(float(thresholds[0])).add(metrics_pred.gt(float(thresholds[1])))
        vigor_image = (
            tercile.remap([0, 1, 2], order)
            .updateMask(classified)
            .rename("vigor_class")
        )

        prediction_collection = ee.ImageCollection(
            [vigor_image.toFloat().set("system:time_start", ee.Date(f"{pred_year}-01-01").millis())]
        )
        dataset = xr.open_dataset(
            prediction_collection, engine="ee", crs=crs, crs_transform=transform, shape_2d=(width, height),
        ).load()
        dataset.attrs["calibration_metric"] = metric_name
        dataset.attrs["calibration_status"] = calibration_status

        vigor_class = dataset["vigor_class"].isel(time=0).values
        source_grid = source_grid_from_dataset(dataset, "vigor_class")

        image = _render_vigor_image(
            roi=roi,
            vigor_class=vigor_class,
            source_grid=source_grid,
            car_code=car_code,
            base_year=pred_year,
            coords=roi.coordinates().getInfo(),
        )
        save_cache(car_code, cache_key, dataset, image, kind="vigor")

        log_info(
            f"[{car_code}] estimate_pasture_vigor {pred_year}: "
            f"calibração={calibration_status}/{metric_name} em {time.perf_counter() - start:.2f}s"
        )

        return VigorAnalysis(
            stats=_vigor_stats_from_areas(_area_by_vigor_class(vigor_class), pred_year),
            image=image,
            pred_year=pred_year,
            train_year=train_year,
            source="on_the_fly",
            cached=False,
            calibration_metric=metric_name,
            calibration_status=calibration_status,
        )

    except ValueError as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] {error}")
    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Falha no Earth Engine ao estimar vigor da pastagem: {error}")
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Erro inesperado ao estimar vigor da pastagem: {error}")


def analyze_pasture_vigor(roi: ee.Geometry, car_code: str, year: int = None) -> VigorAnalysis:
    """Resolve the best available pasture vigor (estimated → MapBiomas)."""
    try:
        return estimate_pasture_vigor(roi=roi, car_code=car_code, pred_year=year)
    except Exception as error:
        log_warning(
            f"[{car_code}] vigor estimado indisponível ({error}); "
            "usando o mapeamento estático do MapBiomas"
        )
        latest_year = latest_asset_year(VIGOR_ASSET, base_year=VIGOR_ASSET_BASE_YEAR)
        target_year = max(
            VIGOR_ASSET_BASE_YEAR, min(year or latest_year, latest_year)
        )
        stats = get_pasture_vigor(roi=roi, year=target_year)
        try:
            image = retrieve_pasture_vigor_image(
                coords=roi.coordinates().getInfo(),
                year=target_year,
                feature_key=car_code,
            )
        except Exception as image_error:
            log_warning(f"[{car_code}] mapa estático de vigor indisponível: {image_error}")
            image = None
        return VigorAnalysis(
            stats=stats,
            image=image,
            pred_year=target_year,
            train_year=None,
            source="mapbiomas",
            cached=False,
        )