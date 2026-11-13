"""Unit tests for the local raster cache/render pipeline (no Earth Engine)."""

import numpy as np
import pytest
import xarray as xr

from domain.services.geospatial import raster_render
from domain.services.geospatial.xee_grid import RasterGrid, resample_nearest


def _grid(transform=(-51.0, 0.0, -51.0, 0.0, 1.0, 1.0), width=2, height=2):
    return RasterGrid(
        crs="EPSG:4326",
        transform=transform,
        width=width,
        height=height,
        scale=1,
    )


def test_continuous_rgba_keeps_nodata_transparent():
    values = np.array([[0.0, np.nan], [10.0, 20.0]])
    rgba = raster_render.continuous_rgba(values, ["#000000", "#ffffff"], 0.0, 20.0)

    assert rgba.shape == (2, 2, 4)
    assert rgba[0, 1, 3] == 0
    assert rgba[1, 0, 3] == 255
    assert tuple(rgba[1, 1, :3]) == (255, 255, 255)


def test_discrete_rgba_maps_only_known_classes():
    values = np.array([[1, 2], [0, 1]])
    rgba = raster_render.discrete_rgba(values, {1: "#00ff00", 2: "#ff0000"})

    assert tuple(rgba[0, 0, :3]) == (0, 255, 0)
    assert tuple(rgba[0, 1, :3]) == (255, 0, 0)
    assert rgba[1, 0, 3] == 0


def test_composite_rgba_blends_by_alpha():
    base = np.zeros((1, 2, 3), dtype=np.uint8)
    overlay = np.zeros((1, 2, 4), dtype=np.uint8)
    overlay[0, 0] = (255, 0, 0, 255)
    overlay[0, 1] = (255, 0, 0, 0)

    result = raster_render.composite_rgba(base, overlay)
    assert tuple(result[0, 0]) == (255, 0, 0)
    assert tuple(result[0, 1]) == (0, 0, 0)


def test_get_base_raster_returns_uint8(monkeypatch):
    from domain.services.geospatial import raster_layers

    dataset = xr.Dataset(
        {
            "r": (("time", "y", "x"), np.array([[[108.0, 100.0], [103.0, 100.0]]], dtype=np.float32)),
            "g": (("time", "y", "x"), np.array([[[72.0, 72.0], [74.0, 74.0]]], dtype=np.float32)),
            "b": (("time", "y", "x"), np.array([[[43.0, 40.0], [43.0, 42.0]]], dtype=np.float32)),
        },
        coords={
            "time": [np.datetime64("2000-01-01")],
            "y": [0.5, -0.5],
            "x": [0.5, 1.5],
        },
    )

    monkeypatch.setattr(raster_layers, "dataset_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(raster_layers, "load_dataset", lambda *args, **kwargs: dataset)

    grid = RasterGrid(
        crs="EPSG:4326",
        transform=(1.0, 0.0, 0.0, 0.0, -1.0, 1.0),
        width=2,
        height=2,
        scale=1,
    )
    result = raster_layers.get_base_raster(
        roi="roi", feature_key="feature", year=2025, grid=grid
    )

    assert result.dtype == np.uint8
    np.testing.assert_array_equal(
        result,
        np.array(
            [
                [[108, 72, 43], [100, 72, 40]],
                [[103, 74, 43], [100, 74, 42]],
            ],
            dtype=np.uint8,
        ),
    )


def test_clean_mask_values_converts_xee_sentinel_to_nan():
    from domain.services.geospatial.raster_layers import clean_mask_values

    result = clean_mask_values(np.array([[0, -32768], [5, -32768]], dtype=np.int16))
    assert np.isnan(result[0, 1])
    assert np.isnan(result[1, 1])
    assert result[0, 0] == 0
    assert result[1, 0] == 5


def test_grid_for_image_size_scales_the_transform():
    from domain.services.geospatial.raster_render import grid_for_image_size

    grid = RasterGrid(
        crs="EPSG:32722",
        transform=(10.0, 0.0, 0.0, 0.0, -10.0, 1130.0),
        width=113,
        height=113,
        scale=10,
    )
    scaled = grid_for_image_size(grid, (512, 256))

    assert scaled.width == 512
    assert scaled.height == 256
    assert scaled.transform[0] == pytest.approx(10.0 * 113 / 512)
    assert scaled.transform[4] == pytest.approx(-10.0 * 113 / 256)
    assert scaled.transform[2] == 0.0
    assert scaled.transform[5] == 1130.0


def test_draw_outline_accepts_polygon_and_multipolygon_coordinates():
    from PIL import Image

    from domain.services.geospatial.raster_render import draw_outline

    grid = RasterGrid(
        crs="EPSG:4326",
        transform=(0.01, 0.0, -51.0, 0.0, -0.01, -15.0),
        width=10,
        height=10,
        scale=1,
    )
    ring = [
        [-51.0, -15.0],
        [-50.95, -15.0],
        [-50.95, -15.05],
        [-51.0, -15.05],
        [-51.0, -15.0],
    ]
    image = Image.new("RGB", (10, 10))

    # Polygon nesting (EE simplifies a one-polygon MultiPolygon to Polygon).
    polygon_result = draw_outline(image.copy(), [ring], grid)
    # MultiPolygon nesting.
    multipolygon_result = draw_outline(image.copy(), [[ring]], grid)

    assert polygon_result.size == (10, 10)
    assert multipolygon_result.size == (10, 10)


def test_resample_nearest_copies_same_grid():
    values = np.array([[1, 2], [3, 4]], dtype=np.int16)
    grid = _grid()
    result = resample_nearest(values, grid, grid)
    np.testing.assert_array_equal(result.astype(int), values)


def test_resample_nearest_maps_target_centres():
    source = _grid()
    target = RasterGrid(
        crs="EPSG:4326",
        transform=(-51.0, 0.0, -51.0, 0.0, 0.5, 1.0),
        width=2,
        height=1,
        scale=1,
    )
    values = np.array([[10, 20], [30, 40]], dtype=np.int16)
    result = resample_nearest(values, source, target)
    np.testing.assert_array_equal(result.astype(int), [[10, 20]])


def test_pasture_mask_reuses_cached_classification(monkeypatch):
    from domain.services.geospatial import pasture_mask

    dataset = xr.Dataset(
        {"pasto": (("time", "y", "x"), np.array([[[1, 0], [1, 0]]], dtype=np.int16))},
        coords={
            "time": [np.datetime64("2000-01-01")],
            "y": [0.5, -0.5],
            "x": [0.5, 1.5],
        },
    )
    dataset["pasto"].attrs["crs"] = "EPSG:4326"

    monkeypatch.setattr(pasture_mask, "dataset_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(pasture_mask, "load_dataset", lambda *args, **kwargs: dataset)
    monkeypatch.setattr(
        pasture_mask,
        "_classify",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not classify")),
    )

    target = RasterGrid(
        crs="EPSG:4326",
        transform=(1.0, 0.0, 0.0, 0.0, -1.0, 1.0),
        width=2,
        height=2,
        scale=1,
    )
    result = pasture_mask.get_pasture_mask_array(
        roi="roi",
        feature_key="feature",
        pred_year=2024,
        train_year=2023,
        grid=target,
    )
    np.testing.assert_array_equal(result.astype(int), [[1, 0], [1, 0]])


def test_t2g_biomass_array_reads_cache_without_gee(monkeypatch):
    from domain.services.geospatial import gee

    dataset = xr.Dataset(
        {"tonC_hec": (("time", "y", "x"), np.ones((1, 2, 2), dtype=np.float32))},
        coords={
            "time": [np.datetime64("2000-01-01")],
            "y": [0.5, -0.5],
            "x": [0.5, 1.5],
        },
    )
    dataset.attrs["target_year"] = 2025
    dataset.attrs["target_month"] = 8

    monkeypatch.setattr(gee, "dataset_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(gee, "load_dataset", lambda *args, **kwargs: dataset)
    monkeypatch.setattr(
        gee,
        "_get_t2g_biomass_image",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not call GEE")),
    )

    grid = RasterGrid(
        crs="EPSG:4326",
        transform=(1.0, 0.0, 0.0, 0.0, -1.0, 1.0),
        width=2,
        height=2,
        scale=1,
    )
    values, target_year, target_month = gee._get_t2g_biomass_array(
        roi="roi",
        feature_key="feature",
        month=9,
        year=2025,
        grid=grid,
    )

    np.testing.assert_array_equal(values.astype(int), [[1, 1], [1, 1]])
    assert (target_year, target_month) == (2025, 8)


def test_get_biomass_applies_cached_pasture_mask(monkeypatch):
    from domain.services.geospatial import gee

    grid = RasterGrid(
        crs="EPSG:4326",
        transform=(10.0, 0.0, 0.0, 0.0, -10.0, 20.0),
        width=2,
        height=2,
        scale=10,
    )
    biomass = np.array([[10.0, 20.0], [30.0, 40.0]], dtype=np.float32)
    pasture = np.array([[1, 0], [1, 1]], dtype=np.int16)

    monkeypatch.setattr(gee, "grid_for_roi", lambda *args, **kwargs: grid)
    monkeypatch.setattr(
        gee, "_get_t2g_biomass_array",
        lambda **kwargs: (biomass, 2025, 8),
    )
    monkeypatch.setattr(
        gee, "_get_pasture_mask_array",
        lambda *args, **kwargs: pasture,
    )

    result = gee.get_biomass("roi", 9, 2025, feature_key="feature")

    assert result.period == "mensal"
    assert result.observation_year == 2025
    assert result.amount.value == pytest.approx(0.8)
