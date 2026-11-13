"""Cached pasture mask used to mask the biomass raster locally."""

from typing import Optional

import ee
import numpy as np

from domain.services.geospatial.pasture_cache import (
    dataset_exists,
    load_dataset,
    save_dataset,
)
from domain.services.geospatial.xee_grid import (
    RasterGrid,
    grid_for_roi,
    resample_nearest,
    source_grid_from_dataset,
)
from domain.services.geospatial.raster_layers import download_image_dataset, layer_cache_key
from domain.services.geospatial.pasture_classification import (
    _CACHE_VERSION,
    _classify,
    _latest_mapbiomas_year,
)

_MASK_CACHE_VERSION = "v1"


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


def get_pasture_mask_array(
    roi: ee.Geometry,
    feature_key: str,
    pred_year: Optional[int] = None,
    train_year: Optional[int] = None,
    grid: Optional[RasterGrid] = None,
) -> np.ndarray:
    """Returns the binary pasture mask on the canonical grid.

    Reuses the classification zarr produced by ``classify_pasture_on_the_fly``
    when available, resampling it to the canonical grid if necessary. Otherwise
    computes the classification once and caches the mask itself.
    """
    train_year = train_year or _latest_mapbiomas_year()
    pred_year = pred_year or (train_year + 1)
    grid = grid or grid_for_roi(roi, scale=10)

    # Existing classification cache (keys before/after the grid hash was added).
    for key in (
        layer_cache_key([pred_year], grid, _CACHE_VERSION),
        f"{pred_year}_{_CACHE_VERSION}",
    ):
        cached = _cached_pasture_array(feature_key, key, grid)
        if cached is not None:
            return cached

    mask_key = layer_cache_key([pred_year], grid, _MASK_CACHE_VERSION)
    if dataset_exists(feature_key, mask_key, kind="pasture_mask"):
        dataset = load_dataset(feature_key, mask_key, kind="pasture_mask")
        return dataset["pasto"].isel(time=0).values

    classified, _embedding = _classify(
        roi=roi,
        train_year=train_year,
        pred_year=pred_year,
    )
    mask_image = classified.gte(1).rename("pasto")
    dataset = download_image_dataset(mask_image, grid, band_name="pasto", dtype="int16")
    dataset.attrs.update(
        {
            "pred_year": int(pred_year),
            "train_year": int(train_year),
            "grid_hash": grid.hash,
        }
    )
    save_dataset(feature_key, mask_key, dataset, kind="pasture_mask")
    return dataset["pasto"].isel(time=0).values
