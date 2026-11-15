import time
import traceback

from typing import Dict, Optional, Tuple

import ee
import numpy as np
import PIL
import xarray as xr

from semente.logging import log_error, log_info

from domain.services.geospatial import raster_layers, raster_render
from domain.services.geospatial.gee import _FEATURE_BUFFER, _IMAGE_DIMENSION
from domain.services.geospatial.pasture_cache import (
    dataset_exists,
    load_dataset,
    save_cache,
)
from domain.services.geospatial.xee_grid import (
    _native_crs,
    _utm_grid,
    grid_for_roi,
    resample_nearest,
    source_grid_from_dataset,
)


_EMBEDDING_ASSET = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
_MAPBIOMAS_ASSET = "projects/mapbiomas-public/assets/brazil/lulc_10m/collection3/mapbiomas_10m_collection3_integration_v1"

_PASTURE_CLASS = 15

_SAMPLE_BUFFER_DISTANCE = 3000

_NUM_POINTS_PASTURE = 600
_NUM_POINTS_NOT_PASTURE = 4400

_RF_TREES = 100

_SCALE = 10

_MASK_VALUE = -32768

# Bump sempre que a lógica de amostragem/treino/classificação mudar — invalida
# cache antigo em vez de servir resultado stale de uma versão anterior do algoritmo.
_CACHE_VERSION = "v2"


def _embedding(roi: ee.Geometry, year: int) -> ee.Image:
    """
    Annual V1 embedding for the given year, in the asset's native CRS.

    Args:
        roi (ee.Geometry): Property geometry (used to filter the collection).
        year (int): Target year.

    Returns:
        ee.Image: First annual image from the GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL
        asset intersecting the roi, without resampling or scaling.
    """
    return (
        ee.ImageCollection(_EMBEDDING_ASSET)
        .filterBounds(roi)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .first()
    )


def _samples(roi: ee.Geometry, train_year: int) -> Tuple[ee.FeatureCollection, ee.List]:
    """
    Sample pasture/not-pasture points using MapBiomas as the label + the training-year embedding.

    Sampling is stratified and balanced per class: `_NUM_POINTS_PASTURE` points
    for pasture (class 1) and `_NUM_POINTS_NOT_PASTURE` for not-pasture (class 0),
    within a `_SAMPLE_BUFFER_DISTANCE` m buffer around the property. `numPoints=0`
    prevents classes outside `classValues` from producing any samples.

    Args:
        roi (ee.Geometry): Property geometry.
        train_year (int): Training year (MapBiomas + embedding).

    Returns:
        Tuple[ee.FeatureCollection, ee.List]: FeatureCollection with the samples
        ("pasto" band + embedding bands) and the list of embedding band names.
    """
    label = (
        ee.Image(_MAPBIOMAS_ASSET)
        .select(f"classification_{train_year}")
        .eq(_PASTURE_CLASS)
        .rename("pasto")
    )
    embedding = _embedding(roi=roi, year=train_year)
    feature_collection = label.addBands(embedding).stratifiedSample(
        numPoints=0,
        classValues=[1, 0],
        classPoints=[_NUM_POINTS_PASTURE, _NUM_POINTS_NOT_PASTURE],
        classBand="pasto",
        region=roi.buffer(_SAMPLE_BUFFER_DISTANCE),
        scale=_SCALE,
        seed=42,
        geometries=False,
    )
    return feature_collection, embedding.bandNames()


def _latest_mapbiomas_year() -> int:
    """
    Most recent year with a 'classification_YYYY' band available in the MapBiomas asset.

    Returns:
        int: Highest year found among the classification bands.
    """
    bands = ee.Image(_MAPBIOMAS_ASSET).bandNames().getInfo()
    years = [int(band.replace("classification_", "")) for band in bands if band.startswith("classification_")]
    return max(years)


def _area_ha_from_pasto(pasto: xr.DataArray) -> float:
    """
    Area in hectares derived from the binary pasture band (1 = pasture).

    Counts pixels equal to 1 and converts to ha using the per-pixel area
    (`_SCALE`² m² → /1e4 ha).

    Args:
        pasto (xr.DataArray): Binary "pasto" band (1 = pasture, 0 = not-pasture).

    Returns:
        float: Pasture area in hectares.
    """
    return float((pasto.values == 1).sum()) * (_SCALE ** 2) / 1e4


def _render_classification_image(
    roi: ee.Geometry,
    pasto,
    source_grid,
    car_code: str,
    base_year: int,
    coords,
) -> "PIL.Image.Image":
    """Renders the cached classification over the cached satellite base."""
    _PASTURE_COLOR = "#00c800"
    render_grid = grid_for_roi(roi, scale=_SCALE, buffer_m=_FEATURE_BUFFER)
    values = resample_nearest(pasto.values, source_grid, render_grid)
    values = np.nan_to_num(values, nan=0).astype(int)

    base_rgb = raster_layers.get_base_raster(
        roi=roi, feature_key=car_code, year=base_year, grid=render_grid
    )
    return raster_render.render_discrete_map(
        base_rgb=base_rgb,
        values=values,
        coords=coords,
        grid=render_grid,
        class_colors={1: _PASTURE_COLOR},
        class_labels={1: "Pastagem"},
        title=f"Classificação de Pastagem ({base_year})",
        dimension=_IMAGE_DIMENSION,
    )


def _classify(roi: ee.Geometry, train_year: int, pred_year: int) -> Tuple[ee.Image, ee.Image]:
    """
    Train the RandomForest on `train_year` samples and classify `pred_year`'s embedding.

    Args:
        roi (ee.Geometry): Property geometry.
        train_year (int): Training year (MapBiomas samples + embedding).
        pred_year (int): Target year for classification.

    Returns:
        Tuple[ee.Image, ee.Image]: (classified binary "pasto" image, the pred_year
        embedding image used for it — reused elsewhere as the CRS/grid reference).
    """
    embedding_check = _embedding(roi=roi, year=pred_year)
    if embedding_check.getInfo() is None:
        raise ValueError(f"Satellite Embedding {pred_year} not yet available for this property.")

    fc, bandnames = _samples(roi=roi, train_year=train_year)
    classifier = ee.Classifier.smileRandomForest(_RF_TREES).train(fc, "pasto", bandnames)
    classified = embedding_check.classify(classifier).rename("pasto").clip(roi)

    return classified, embedding_check


def classify_pasture_on_the_fly(roi: ee.Geometry, car_code: str, pred_year: int = None, train_year: int = None) -> Dict:
    """
    Classify pasture/not-pasture for the most recent available year and map the property.

    The classification runs entirely on GEE (server-side, `smileRandomForest`,
    trained with MapBiomas samples + Satellite Embedding for the training year)
    and predicts over the embedding of the following year. Xee only downloads
    the resulting raster (a single binary band) into a zarr + png cache
    (`pasture_cache_storage`: local `tmp/` in `development`, S3 bucket in
    `production`/`stagging`) — subsequent calls for the same property/year read
    the cache and do not touch GEE.

    Args:
        roi (ee.Geometry): Property geometry (MultiPolygon).
        car_code (str): CAR code(s) of the property — used as the cache key.
        pred_year (int, optional): Target year for classification. Defaults to train_year + 1.
        train_year (int, optional): Training year (MapBiomas samples + embedding). Defaults to the most recent year available in MapBiomas.

    Returns:
        Dict: {"area_pasto_ha", "pred_year", "train_year", "cached", "imagem"} —
        "imagem" is a PIL.Image.Image ready to be sent.
    """
    try:
        train_year = train_year or _latest_mapbiomas_year()
        pred_year = pred_year or (train_year + 1)
        cache_key = f"{pred_year}_{_CACHE_VERSION}"

        if dataset_exists(car_code, cache_key, kind="pasture"):
            dataset = load_dataset(car_code, cache_key, kind="pasture")
            pasto = dataset["pasto"].isel(time=0)
            area_ha = _area_ha_from_pasto(pasto)
            source_grid = source_grid_from_dataset(dataset, "pasto")
            image = _render_classification_image(
                roi=roi,
                pasto=pasto,
                source_grid=source_grid,
                car_code=car_code,
                base_year=pred_year,
                coords=roi.coordinates().getInfo(),
            )
            log_info(f"[{car_code}] pasture cache hit ({pred_year}): {area_ha} ha")
            return {
                "imagem": image,
                "area_pasto_ha": round(area_ha, 4),
                "pred_year": pred_year,
                "train_year": train_year,
                "cached": True, 
            }

        start = time.perf_counter()

        classified, embedding_check = _classify(roi=roi, train_year=train_year, pred_year=pred_year)

        ts = ee.Date(f"{pred_year}-01-01").millis()
        collection = ee.ImageCollection([classified.set("system:time_start", ts)])
        crs = _native_crs(embedding_check)
        transform, width, height = _utm_grid(roi=roi, crs=crs, scale=_SCALE)

        dataset = xr.open_dataset(
            collection, engine="ee", crs=crs, crs_transform=transform,
            shape_2d=(width, height), mask_and_scale=False, ee_mask_value=_MASK_VALUE,
        ).load()
        dataset = dataset.fillna(_MASK_VALUE).astype("int16")

        pasto = dataset["pasto"].isel(time=0)
        area_ha = _area_ha_from_pasto(pasto)
        source_grid = source_grid_from_dataset(dataset, "pasto")

        image = _render_classification_image(
            roi=roi,
            pasto=pasto,
            source_grid=source_grid,
            car_code=car_code,
            base_year=pred_year,
            coords=roi.coordinates().getInfo(),
        )
        save_cache(car_code, cache_key, dataset, image)

        log_info(f"[{car_code}] classify_pasture_on_the_fly {pred_year}: {area_ha} ha em {time.perf_counter() - start:.2f}s")

        return {
            "imagem": image,
            "area_pasto_ha": round(area_ha, 4),
            "pred_year": pred_year,
            "train_year": train_year,
            "cached": False, 
        }

    except ValueError as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] {error}")
    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Earth Engine failed while classifying pasture: {error}")
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Unexpected error while classifying pasture: {error}")

def get_on_the_fly_pasture_mask(roi: ee.Geometry, pred_year: int = None, train_year: int = None) -> Optional[ee.Image]:
    """
    Classificação de pastagem on-the-fly (mesmos anos padrão do mapa) como máscara binária
    lazy, sem download nem cache, para aplicar em outras camadas (ex.: biomassa Time2Graze).

    Returns:
        Optional[ee.Image]: Máscara (1 = pastagem), ou None se a classificação estiver
        indisponível — o chamador deve cair pro mapa de pastagem estático do GPW.
    """
    try:
        train_year = train_year or _latest_mapbiomas_year()
        classified, _ = _classify(roi=roi, train_year=train_year, pred_year=pred_year or (train_year + 1))
        return classified.gte(1)
    except Exception as error:
        log_error(f"get_on_the_fly_pasture_mask: classificação indisponível, usando o mapa GPW ({error})")
        return None
