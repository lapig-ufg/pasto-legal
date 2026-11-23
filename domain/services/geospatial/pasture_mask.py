"""Cached pasture mask used to mask the biomass raster locally.

The mask comes from a per-pixel classification, so it is speckled at 10 m.
It is regularised once with ``clean_mask`` before being cached: without that,
rendering at the native grid resolution shows confetti instead of fields.
"""

from typing import Optional

import ee
import numpy as np

from semente.logging import log_warning

from domain.services.geospatial.pasture_cache import (
    dataset_exists,
    load_dataset,
    save_dataset,
)
from domain.services.geospatial.mapbiomas import latest_classification_year
from domain.services.geospatial.xee_grid import (
    RasterGrid,
    grid_for_roi,
    resample_nearest,
    source_grid_from_dataset,
)
from domain.services.geospatial.raster_layers import download_image_dataset, layer_cache_key
from domain.services.geospatial.raster_render import clean_mask
from domain.services.geospatial.pasture_classification import (
    _CACHE_VERSION,
    _classify_cached,
    _static_pasture_image,
)

_MASK_CACHE_VERSION = "v2"


def _cached_pasture_array(
    feature_key: str,
    key: str,
    grid: RasterGrid,
) -> Optional[np.ndarray]:
    if not dataset_exists(feature_key, key, kind="pasture"):
        return None

    try:
        dataset = load_dataset(feature_key, key, kind="pasture")
        source = dataset["pasto"].isel(time=0).values
        source_grid = source_grid_from_dataset(dataset, "pasto")
        return resample_nearest(source, source_grid, grid)
    except Exception:
        return None


def _static_pasture_mask_array(
    roi: ee.Geometry,
    feature_key: str,
    pred_year: int,
    grid: RasterGrid,
) -> np.ndarray:
    """MapBiomas static pasture mask on the canonical grid."""
    latest_year = latest_classification_year()
    target_year = min(pred_year, latest_year)
    mask_key = layer_cache_key([f"static_{target_year}"], grid, _MASK_CACHE_VERSION)

    if dataset_exists(feature_key, mask_key, kind="pasture_mask"):
        dataset = load_dataset(feature_key, mask_key, kind="pasture_mask")
        return dataset["pasto"].isel(time=0).values == 1

    mask_image = _static_pasture_image(roi, target_year).rename("pasto")
    dataset = download_image_dataset(mask_image, grid, band_name="pasto", dtype="int16")
    cleaned = clean_mask(dataset["pasto"].isel(time=0).values)
    cleaned_data = cleaned.astype("int16")[np.newaxis, :, :]
    dataset = dataset.assign(pasto=dataset["pasto"].copy(data=cleaned_data))
    dataset.attrs.update(
        {
            "pred_year": int(target_year),
            "train_year": None,
            "grid_hash": grid.hash,
            "cleaned": True,
            "source": "mapbiomas",
        }
    )
    save_dataset(feature_key, mask_key, dataset, kind="pasture_mask")
    return cleaned


def get_pasture_mask_array(
    roi: ee.Geometry,
    feature_key: str,
    pred_year: Optional[int] = None,
    train_year: Optional[int] = None,
    grid: Optional[RasterGrid] = None,
) -> np.ndarray:
    """Returns the binary pasture mask on the canonical grid.

    Reuses the classification zarr produced by ``classify_pasture`` when
    available, resampling it to the canonical grid if necessary. Otherwise
    computes the classification once and caches the mask itself. If the
    on-the-fly classification is unavailable, falls back to the static
    MapBiomas pasture map instead of returning an all-ones mask.
    """
    train_year = train_year or latest_classification_year()
    pred_year = pred_year or (train_year + 1)
    grid = grid or grid_for_roi(roi, scale=10)

    # Existing classification cache (keys before/after the grid hash was added).
    for key in (
        layer_cache_key([pred_year], grid, _CACHE_VERSION),
        f"{pred_year}_{_CACHE_VERSION}",
    ):
        cached = _cached_pasture_array(feature_key, key, grid)
        if cached is not None:
            return clean_mask(cached)

    mask_key = layer_cache_key([pred_year], grid, _MASK_CACHE_VERSION)
    if dataset_exists(feature_key, mask_key, kind="pasture_mask"):
        dataset = load_dataset(feature_key, mask_key, kind="pasture_mask")
        # Stored masks are already cleaned (see below).
        return dataset["pasto"].isel(time=0).values == 1

    try:
        classified, _embedding = _classify_cached(
            roi=roi,
            car_code=feature_key,
            train_year=train_year,
            pred_year=pred_year,
        )
    except Exception as error:
        log_warning(
            f"[{feature_key}] máscara de pastagem indisponível ({error}); "
            "usando o mapeamento estático do MapBiomas"
        )
        return _static_pasture_mask_array(roi, feature_key, pred_year, grid)

    mask_image = classified.gte(1).rename("pasto")
    dataset = download_image_dataset(mask_image, grid, band_name="pasto", dtype="int16")
    cleaned = clean_mask(dataset["pasto"].isel(time=0).values)
    cleaned_data = cleaned.astype("int16")[np.newaxis, :, :]
    dataset = dataset.assign(pasto=dataset["pasto"].copy(data=cleaned_data))
    dataset.attrs.update(
        {
            "pred_year": int(pred_year),
            "train_year": int(train_year),
            "grid_hash": grid.hash,
            "cleaned": True,
            "source": "on_the_fly",
        }
    )
    save_dataset(feature_key, mask_key, dataset, kind="pasture_mask")
    return cleaned
