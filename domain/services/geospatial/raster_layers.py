"""Cached GEE raster layers and the canonical satellite visualization.

Every layer is downloaded once through Xee into a zarr store on S3/local disk
and then reused by the local renderer. No `getThumbURL`/PNG generation happens
in Earth Engine.
"""

import datetime
import hashlib
import json
from typing import Callable, Optional, Sequence, Tuple

import ee
import numpy as np
import xarray as xr

from domain.services.geospatial.pasture_cache import (
    dataset_exists,
    load_dataset,
    save_dataset,
)
from domain.services.geospatial.xee_grid import RasterGrid, grid_for_roi

_SATELLITE_CACHE_VERSION = "v1"

_MASK_VALUE = -32768


def clean_mask_values(values: np.ndarray, mask_value: int = _MASK_VALUE) -> np.ndarray:
    """Converts the xee mask sentinel into NaN for continuous arrays."""
    values = np.asarray(values)
    if np.issubdtype(values.dtype, np.integer):
        values = values.astype(np.float64)
    return np.where(values == mask_value, np.nan, values)


def feature_key_from_coords(coords) -> str:
    """Stable cache key for callers that only have a geometry."""
    payload = json.dumps(coords, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _grid_attrs(grid: RasterGrid) -> dict:
    return {
        "crs": grid.crs,
        "transform": json.dumps(list(grid.transform)),
        "width": int(grid.width),
        "height": int(grid.height),
        "scale": int(grid.scale),
        "grid_hash": grid.hash,
    }


def download_image_dataset(
    image: ee.Image,
    grid: RasterGrid,
    band_name: Optional[str] = None,
    time_start: str = "2000-01-01",
    dtype: Optional[str] = None,
) -> xr.Dataset:
    """Downloads a single EE image into a zarr-backed xarray dataset."""
    if band_name:
        image = image.select([0], [band_name])

    collection = ee.ImageCollection(
        [image.set("system:time_start", ee.Date(time_start).millis())]
    )
    dataset = xr.open_dataset(
        collection,
        engine="ee",
        crs=grid.crs,
        crs_transform=grid.transform,
        shape_2d=(grid.width, grid.height),
        mask_and_scale=False,
        ee_mask_value=-32768,
    ).load()

    if dtype:
        dataset = dataset.astype(dtype)

    dataset.attrs.update(_grid_attrs(grid))
    dataset.attrs["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return dataset


def get_cached_layer_array(
    feature_key: str,
    kind: str,
    key: str,
    grid: RasterGrid,
    loader: Callable[[], xr.Dataset],
    band_name: str,
) -> np.ndarray:
    """Reads a layer array from the cache, or downloads and stores it."""
    if dataset_exists(feature_key, key, kind=kind):
        dataset = load_dataset(feature_key, key, kind=kind)
    else:
        dataset = loader()
        dataset.attrs.update(_grid_attrs(grid))
        save_dataset(feature_key, key, dataset, kind=kind)

    return clean_mask_values(dataset[band_name].isel(time=0).values)


def get_base_raster(
    roi: ee.Geometry,
    feature_key: str,
    year: Optional[int] = None,
    grid: Optional[RasterGrid] = None,
    dimension_scale: int = 10,
) -> np.ndarray:
    """Returns the cached satellite RGB visualization for the property/year."""
    from domain.services.geospatial.gee import _get_base_image

    grid = grid or grid_for_roi(roi, scale=dimension_scale)
    today = datetime.date.today()
    if year is None or year >= today.year:
        date_key = f"{year or today.year}-{today.month:02d}"
    else:
        date_key = str(year)
    key = f"{date_key}_{_SATELLITE_CACHE_VERSION}_{grid.hash}"

    def _loader() -> xr.Dataset:
        base_image = _get_base_image(roi=roi, year=year).select(
            [0, 1, 2], ["r", "g", "b"]
        )
        return download_image_dataset(base_image, grid)

    if dataset_exists(feature_key, key, kind="satellite"):
        dataset = load_dataset(feature_key, key, kind="satellite")
    else:
        dataset = _loader()
        save_dataset(feature_key, key, dataset, kind="satellite")

    base_rgb = np.stack(
        [
            dataset["r"].isel(time=0).values,
            dataset["g"].isel(time=0).values,
            dataset["b"].isel(time=0).values,
        ],
        axis=-1,
    )
    # PIL.Image.fromarray(mode="RGB") requires uint8; the zarr may store the
    # visualization bands as float32, which otherwise produces garbage pixels.
    return np.clip(base_rgb, 0, 255).astype(np.uint8)


def get_layer_array(
    roi: ee.Geometry,
    feature_key: str,
    kind: str,
    key: str,
    image_factory: Callable[[], ee.Image],
    band_name: str,
    grid: Optional[RasterGrid] = None,
    scale: int = 10,
) -> Tuple[np.ndarray, RasterGrid]:
    """Returns a cached numeric layer array and the grid it belongs to."""
    grid = grid or grid_for_roi(roi, scale=scale)

    def _loader() -> xr.Dataset:
        return download_image_dataset(image_factory(), grid, band_name=band_name)

    values = get_cached_layer_array(
        feature_key=feature_key,
        kind=kind,
        key=key,
        grid=grid,
        loader=_loader,
        band_name=band_name,
    )
    return values, grid


def layer_cache_key(
    key_parts: Sequence[object],
    grid: RasterGrid,
    version: str,
) -> str:
    """Builds a cache key that always includes the canonical grid hash."""
    parts = [str(part) for part in key_parts] + [version, grid.hash]
    return "_".join(parts)
