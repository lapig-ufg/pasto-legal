import time
import traceback

from io import BytesIO
from typing import Dict, Tuple

import affine
import ee
import PIL
import requests
import xarray as xr

from agno.utils.log import log_error, log_info

from app.services.geospatial.gee import _FEATURE_BUFFER, _IMAGE_DIMENSION, _draw_feature_boundaries, _get_base_image
from app.services.geospatial.pasture_cache import cache_exists, load_cache, save_cache


_EMBEDDING_ASSET = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
_MAPBIOMAS_ASSET = "projects/mapbiomas-public/assets/brazil/lulc_10m/collection3/mapbiomas_10m_collection3_integration_v1"

_PASTURE_CLASS = 15

_SAMPLE_BUFFER_DISTANCE = 3000

_NUM_POINTS_PASTURE = 600
_NUM_POINTS_NOT_PASTURE = 4400

_RF_TREES = 100

_SCALE = 10

_MASK_VALUE = -32768


def _utm_grid(roi: ee.Geometry, crs: str, scale: int) -> Tuple[affine.Affine, int, int]:
    """
    Compute the pixel grid for the property's bounding box projected onto the target CRS.

    The Xee API (0.1.1) requires the explicit grid (crs_transform + shape_2d)
    instead of scale/geometry, so we derive the affine transform and dimensions.

    Args:
        roi (ee.Geometry): Property geometry.
        crs (str): Target metric CRS (e.g. "EPSG:32722").
        scale (int): Pixel size in meters.

    Returns:
        Tuple[affine.Affine, int, int]: transform, width (x) and height (y) in pixels.
    """
    projection = ee.Projection(crs)
    ring = ee.List(roi.bounds(1).transform(projection, 1).coordinates().get(0)).getInfo()

    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]

    x_min = (min(xs) // scale) * scale
    x_max = -(-max(xs) // scale) * scale
    y_min = (min(ys) // scale) * scale
    y_max = -(-max(ys) // scale) * scale

    width = round((x_max - x_min) / scale)
    height = round((y_max - y_min) / scale)
    transform = affine.Affine(scale, 0, x_min, 0, -scale, y_max)

    return transform, width, height


def _native_crs(collection: ee.ImageCollection) -> str:
    """Return the native (metric) CRS of the first image in the collection."""
    return collection.select(0).projection().getInfo()["crs"]


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
    emb = _embedding(roi=roi, year=train_year)
    fc = label.addBands(emb).stratifiedSample(
        numPoints=0,
        classValues=[1, 0],
        classPoints=[_NUM_POINTS_PASTURE, _NUM_POINTS_NOT_PASTURE],
        classBand="pasto",
        region=roi.buffer(_SAMPLE_BUFFER_DISTANCE),
        scale=_SCALE,
        seed=42,
        geometries=False,
    )
    return fc, emb.bandNames()


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


def _render_classification_image(roi: ee.Geometry, classified: ee.Image, base_year: int) -> "PIL.Image.Image":
    """
    Overlay the classified pasture (green) on the satellite image + property boundary.

    Blends the classified raster (masked to show only pasture) with the base
    satellite image for `base_year` and the property boundary, clipped to the
    property buffer, and downloads the result as a PNG via getThumbURL.

    Args:
        roi (ee.Geometry): Property geometry.
        classified (ee.Image): Binary "pasto" image (1 = pasture).
        base_year (int): Year of the base satellite image.

    Returns:
        PIL.Image.Image: PNG ready to be sent.
    """
    overlay = classified.selfMask().visualize(palette=["00c800"])
    base = _get_base_image(roi=roi, year=base_year)
    boundary = _draw_feature_boundaries(roi=roi)

    final_image = base.blend(overlay).blend(boundary).clip(roi.buffer(_FEATURE_BUFFER).bounds())
    url = final_image.getThumbURL({"dimensions": _IMAGE_DIMENSION, "format": "png"})

    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return PIL.Image.open(BytesIO(response.content))


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

        if cache_exists(car_code, pred_year):
            dataset, image = load_cache(car_code, pred_year)
            pasto = dataset["pasto"].isel(time=0)
            area_ha = _area_ha_from_pasto(pasto)
            log_info(f"[{car_code}] pasture cache hit ({pred_year}): {area_ha} ha")
            return {
                "imagem": image,
                "area_pasto_ha": round(area_ha, 4),
                "pred_year": pred_year,
                "train_year": train_year,
                "cached": True, 
            }

        start = time.perf_counter()

        embedding_check = _embedding(roi=roi, year=pred_year)
        if embedding_check.getInfo() is None:
            raise ValueError(f"Satellite Embedding {pred_year} not yet available for this property.")

        fc, bandnames = _samples(roi=roi, train_year=train_year)
        classifier = ee.Classifier.smileRandomForest(_RF_TREES).train(fc, "pasto", bandnames)
        classified = (embedding_check.classify(classifier).rename("pasto").clip(roi))

        ts = ee.Date(f"{pred_year}-01-01").millis()
        collection = ee.ImageCollection([classified.set("system:time_start", ts)])
        crs = _native_crs(embedding_check)
        transform, width, height = _utm_grid(roi=roi, crs=crs, scale=_SCALE)

        dataset = xr.open_dataset(
            collection, engine="ee", crs=crs, crs_transform=transform,
            shape_2d=(width, height), mask_and_scale=False, ee_mask_value=_MASK_VALUE,
        ).load().astype("int16")

        pasto = dataset["pasto"].isel(time=0)
        area_ha = _area_ha_from_pasto(pasto)

        image = _render_classification_image(roi=roi, classified=classified, base_year=pred_year)
        save_cache(car_code, pred_year, dataset, image)

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
