"""Reads the seasonal onset/end GeoTIFF rasters and converts pixel DOY
values into full calendar dates for the 2026/2027 hydrological year.

The rasters are small (122x121, float32, EPSG:4326) and can be read with
PIL alone, so we avoid the heavy rasterio/gdal dependency.

Hydrological-year convention used here:
    * onset_doy_2026: DOY <= 76  -> date in 2027, DOY > 76 -> date in 2026.
    * end_doy_2026:   all DOY values -> date in 2027.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from agno.utils.log import log_error, log_warning


_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
ONSET_RASTER_PATH = _DATA_DIR / "onset_doy_2026.tif"
END_RASTER_PATH = _DATA_DIR / "end_doy_2026.tif"

# Raster geometry (parsed from TIFF tags 33550/33922 - same for both files).
_LON0 = -74.165
_LAT0 = 5.665
_PIXEL = 0.33
_NODATA = -9999

# Base calendar year of the hydrological year.
_BASE_YEAR = 2026

# DOY above this threshold belongs to the first calendar year (2026);
# DOY at or below it rolls into the next calendar year (2027).
_ONSET_HIGH_DOY_THRESHOLD = 76
# End-of-rains DOY values always fall in the next calendar year (2027),
# so the threshold is set above the maximum possible DOY (365).
_END_HIGH_DOY_THRESHOLD = 365


def _load_array(path: Path) -> np.ndarray:
    """Opens the GeoTIFF as a 2D float32 numpy array (rows=lat, cols=lon)."""
    return np.asarray(Image.open(path), dtype=np.float32)


def _sample_pixel(path: Path, latitude: float, longitude: float) -> float | None:
    """Returns the pixel value at (latitude, longitude) or None if the
    coordinate falls outside the raster or hits a NoData pixel."""
    try:
        arr = _load_array(path)
    except Exception as error:
        log_error(f"season_forecast: could not open {path.name}: {error}")
        return None

    n_rows, n_cols = arr.shape
    col = int(round((longitude - _LON0) / _PIXEL))
    row = int(round((_LAT0 - latitude) / _PIXEL))

    if not (0 <= row < n_rows and 0 <= col < n_cols):
        log_warning(
            f"season_forecast: coordinate ({latitude}, {longitude}) "
            f"outside raster extent {path.name}"
        )
        return None

    value = float(arr[row, col])
    if value == _NODATA or np.isnan(value):
        return None
    return value


def doy_to_date(
    doy: int,
    high_doy_threshold: int = _ONSET_HIGH_DOY_THRESHOLD,
    base_year: int = _BASE_YEAR,
) -> datetime.date:
    """Converts a Day-of-Year value into a calendar date.

    DOY above ``high_doy_threshold`` -> same calendar year (base_year).
    DOY at or below ``high_doy_threshold`` -> next calendar year (base_year + 1).
    """
    year = base_year if doy > high_doy_threshold else base_year + 1
    return datetime.date(year, 1, 1) + datetime.timedelta(days=doy - 1)


def get_rain_onset(
    latitude: float, longitude: float, current_date: datetime.date
) -> str:
    """Predicts the start of the rainy season for the given coordinate."""
    onset_doy = _sample_pixel(ONSET_RASTER_PATH, latitude, longitude)
    if onset_doy is None:
        return (
            "Não há previsão de início da estação chuvosa disponível "
            "para esta localização."
        )

    onset_date = doy_to_date(int(onset_doy), _ONSET_HIGH_DOY_THRESHOLD)
    if current_date >= onset_date:
        return "The rainy season has already begun for this location."
    return onset_date.isoformat()


def get_dry_season_onset(
    latitude: float, longitude: float, current_date: datetime.date
) -> str:
    """Predicts the start of the dry season (end of rains) for the coordinate."""
    end_doy = _sample_pixel(END_RASTER_PATH, latitude, longitude)
    if end_doy is None:
        return (
            "The forecast horizon does not currently extend far enough to "
            "determine the end date consistently."
        )

    end_date = doy_to_date(int(end_doy), _END_HIGH_DOY_THRESHOLD)
    if current_date >= end_date:
        return "The dry season is currently underway."
    return end_date.isoformat()