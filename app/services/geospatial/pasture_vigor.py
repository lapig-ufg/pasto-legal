import math
import time
import traceback

from io import BytesIO
from typing import Dict, List, Tuple

import ee
import numpy as np
import PIL.Image
import requests
import xarray as xr

from agno.utils.log import log_error, log_info, log_warning

from app.services.geospatial.gee import _FEATURE_BUFFER, _IMAGE_DIMENSION, _draw_feature_boundaries, _get_base_image
from app.services.geospatial.image import append_discrete_legend
from app.services.geospatial.pasture_cache import cache_exists, load_cache, save_cache
from app.services.geospatial.pasture_classification import (
    _MAPBIOMAS_ASSET,
    _PASTURE_CLASS,
    _classify,
    _latest_mapbiomas_year,
)
from app.services.geospatial.xee_grid import _native_crs, _utm_grid


_MAPBIOMAS_VIGOR_ASSET = "projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_vigor_v3"

_S2_ASSET = "COPERNICUS/S2_SR_HARMONIZED"

_CLOUD_SCORE_ASSET = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"

_CS_CDF_THRESHOLD = 0.60

_SCALE = 10

_MIN_PIXELS_PER_CLASS = 30

# Limiares fixos de amplitude (NDVI) usados só quando a calibração por propriedade
# não é confiável (poucos pixels por classe ou propriedade sem as 3 classes do
# MapBiomas presentes) — estimativa grosseira p/ pastagem no Cerrado, não substitui
# a metodologia oficial do MapBiomas.
_FALLBACK_AMPLITUDE_THRESHOLDS = [0.08, 0.18]

_VIGOR_DICT = {
    1: "Baixo: pastagens com baixo vigor vegetativo e indícios de degradação severa, potencialmente biológica.",
    2: "Médio: pastagens com médio vigor vegativo e indícios de degração moderada.",
    3: "Alto: pastagens com alto vigor vegetativo.",
}

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

    harmonic_collection = (
        ee.ImageCollection(_S2_ASSET)
        .linkCollection(ee.ImageCollection(_CLOUD_SCORE_ASSET), ["cs_cdf"])
        .filterBounds(roi)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
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
) -> Tuple[List[float], str, str]:
    """
    Deriva 2 limiares que separam as 3 classes estáticas do MapBiomas (no ano de
    treino, dentro da própria propriedade) usando a métrica (amplitude ou
    mean_ndvi) com melhor separação entre classes.

    Returns:
        Tuple[List[float], str, str]: (limiares ordenados, nome da métrica escolhida,
        "mapbiomas_<ano>" ou "fallback").
    """
    valid = ~np.isnan(static_class)

    best_metric_name, best_thresholds, best_score = None, None, -math.inf

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
            best_metric_name, best_thresholds, best_score = metric_name, thresholds, score

    if best_metric_name is None:
        return list(_FALLBACK_AMPLITUDE_THRESHOLDS), "amplitude", "fallback"

    return best_thresholds, best_metric_name, "calibrated"


def _area_by_vigor_class(vigor_class: np.ndarray) -> Dict[str, float]:
    valid = vigor_class[~np.isnan(vigor_class)]
    pixel_area_ha = (_SCALE ** 2) / 1e4

    result = {}
    for class_id in (1, 2, 3):
        count = int((valid == class_id).sum())
        if count:
            result[_VIGOR_DICT[class_id]] = round(count * pixel_area_ha, 4)
    return result


def _render_vigor_image(roi: ee.Geometry, vigor_image: ee.Image, base_year: int) -> "PIL.Image.Image":
    palette_dict = {"Baixo": _VIGOR_PALETTE[0], "Médio": _VIGOR_PALETTE[1], "Alto": _VIGOR_PALETTE[2]}

    overlay = vigor_image.visualize(min=1, max=3, palette=_VIGOR_PALETTE)
    base = _get_base_image(roi=roi, year=base_year)
    boundary = _draw_feature_boundaries(roi=roi)

    final_image = base.blend(overlay).blend(boundary).clip(roi.buffer(_FEATURE_BUFFER).bounds())
    url = final_image.getThumbURL({"dimensions": _IMAGE_DIMENSION, "format": "png"})

    response = requests.get(url, timeout=60)
    response.raise_for_status()

    img_pil = PIL.Image.open(BytesIO(response.content))
    return append_discrete_legend(img_pil, "Vigor da Pastagem (estimativa)", palette_dict)


def estimate_pasture_vigor_on_the_fly(roi: ee.Geometry, car_code: str, pred_year: int = None, train_year: int = None) -> Dict:
    """
    Vigor de pastagem on-the-fly: heurística baseada em regressão harmônica sobre
    NDVI (Sentinel-2 + Cloud Score+), calibrada por propriedade contra o asset
    estático do MapBiomas (`pasture_vigor_v3`) no ano de treino, e aplicada à
    classificação de pastagem on-the-fly do ano seguinte.

    IMPORTANTE: é uma estimativa própria, não a metodologia oficial do MapBiomas —
    quando não há pixels suficientes por classe pra calibrar dentro da propriedade,
    cai num limiar fixo aproximado (`calibration_status == "fallback"`).

    Args:
        roi (ee.Geometry): Geometria do imóvel (MultiPolygon).
        car_code (str): Código(s) CAR do imóvel — usado como chave de cache.
        pred_year (int, optional): Ano alvo do vigor. Default: train_year + 1.
        train_year (int, optional): Ano-base (calibração). Default: ano mais recente disponível no MapBiomas.

    Returns:
        Dict: {"area_by_vigor_class_ha", "calibration_metric", "calibration_status",
        "pred_year", "train_year", "cached", "imagem"}
    """
    try:
        train_year = train_year or _latest_mapbiomas_year()
        pred_year = pred_year or (train_year + 1)
        cache_key = pred_year

        if cache_exists(car_code, cache_key, kind="vigor"):
            dataset, image = load_cache(car_code, cache_key, kind="vigor")
            vigor_class = dataset["vigor_class"].isel(time=0).values
            log_info(f"[{car_code}] pasture vigor cache hit ({pred_year})")
            return {
                "imagem": image,
                "area_by_vigor_class_ha": _area_by_vigor_class(vigor_class),
                "calibration_metric": dataset.attrs.get("calibration_metric"),
                "calibration_status": dataset.attrs.get("calibration_status"),
                "pred_year": pred_year,
                "train_year": train_year,
                "cached": True,
            }

        start = time.perf_counter()

        classified, embedding_check = _classify(roi=roi, train_year=train_year, pred_year=pred_year)
        crs = _native_crs(embedding_check)
        transform, width, height = _utm_grid(roi=roi, crs=crs, scale=_SCALE)

        was_pasture_train = (
            ee.Image(_MAPBIOMAS_ASSET).select(f"classification_{train_year}").eq(_PASTURE_CLASS)
        )
        static_vigor_train = ee.Image(_MAPBIOMAS_VIGOR_ASSET).select(train_year - 2000).rename("static_class")
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

        thresholds, metric_name, calibration_status = _calibrate_thresholds(
            static_class=calibration_dataset["static_class"].isel(time=0).values,
            amplitude=calibration_dataset["amplitude"].isel(time=0).values,
            mean_ndvi=calibration_dataset["mean_ndvi"].isel(time=0).values,
        )
        if calibration_status == "fallback":
            log_warning(f"[{car_code}] vigor: calibração por propriedade indisponível, usando limiar fixo")

        metrics_pred = _vigor_metrics_image(roi=roi, year=pred_year).select(metric_name)
        vigor_image = (
            metrics_pred.gt(float(thresholds[0])).add(metrics_pred.gt(float(thresholds[1]))).add(1)
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

        image = _render_vigor_image(roi=roi, vigor_image=vigor_image, base_year=pred_year)
        save_cache(car_code, cache_key, dataset, image, kind="vigor")

        log_info(
            f"[{car_code}] estimate_pasture_vigor_on_the_fly {pred_year}: "
            f"calibração={calibration_status}/{metric_name} em {time.perf_counter() - start:.2f}s"
        )

        return {
            "imagem": image,
            "area_by_vigor_class_ha": _area_by_vigor_class(vigor_class),
            "calibration_metric": metric_name,
            "calibration_status": calibration_status,
            "pred_year": pred_year,
            "train_year": train_year,
            "cached": False,
        }

    except ValueError as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] {error}")
    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Falha no Earth Engine ao estimar vigor da pastagem: {error}")
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Erro inesperado ao estimar vigor da pastagem: {error}")
