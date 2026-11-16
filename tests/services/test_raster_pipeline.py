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

    values = np.zeros((12, 12), dtype=np.int16)
    values[3:9, 3:9] = 1  # one solid field
    dataset = xr.Dataset(
        {"pasto": (("time", "y", "x"), values[np.newaxis, :, :])},
        coords={
            "time": [np.datetime64("2000-01-01")],
            "y": np.arange(12)[::-1] + 0.5,
            "x": np.arange(12) + 0.5,
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
        transform=(1.0, 0.0, 0.0, 0.0, -1.0, 12.0),
        width=12,
        height=12,
        scale=1,
    )
    result = pasture_mask.get_pasture_mask_array(
        roi="roi",
        feature_key="feature",
        pred_year=2024,
        train_year=2023,
        grid=target,
    )
    # The field survives (its 1-px corners are rounded by the median filter).
    assert result[4:8, 4:8].all()
    assert not result[:2].any()
    assert 30 <= int(result.sum()) <= 36


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


def test_reference_month_candidates_retreats_and_wraps_the_year():
    from domain.services.geospatial import gee

    assert gee._reference_month_candidates(2026, 1, 2) == [
        (2026, 1),
        (2025, 12),
        (2025, 11),
    ]
    assert gee._reference_month_candidates(2026, 11, 0) == [(2026, 11)]


def test_month_period_uses_the_month_itself():
    import datetime

    from domain.services.geospatial import gee

    assert gee._month_period(2026, 8) == (
        datetime.date(2026, 8, 1),
        datetime.date(2026, 9, 1),
    )
    assert gee._month_period(2026, 12) == (
        datetime.date(2026, 12, 1),
        datetime.date(2027, 1, 1),
    )


def test_t2g_biomass_array_uses_the_requested_month_and_retries_previous_months(monkeypatch):
    from domain.services.geospatial import gee

    calls = []

    def fake_image(
        roi, start_year, start_month, start_day,
        end_year, end_month, end_day, apply_mask=True,
    ):
        calls.append((start_year, start_month))
        if (start_year, start_month) == (2026, 9):
            return "image", 2026, 9
        return None

    dataset = xr.Dataset(
        {"tonC_hec": (("time", "y", "x"), np.ones((1, 2, 2), dtype=np.float32))},
        coords={
            "time": [np.datetime64("2000-01-01")],
            "y": [0.5, -0.5],
            "x": [0.5, 1.5],
        },
    )
    grid = RasterGrid(
        crs="EPSG:4326",
        transform=(1.0, 0.0, 0.0, 0.0, -1.0, 1.0),
        width=2,
        height=2,
        scale=1,
    )

    monkeypatch.setattr(gee, "_get_t2g_biomass_image", fake_image)
    monkeypatch.setattr(gee, "dataset_exists", lambda *args, **kwargs: False)
    monkeypatch.setattr(gee, "save_dataset", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        gee.raster_layers, "download_image_dataset", lambda *args, **kwargs: dataset
    )

    values, target_year, target_month = gee._get_t2g_biomass_array(
        roi="roi", feature_key="feature", month=11, year=2026, grid=grid,
        max_fallbacks=2,
    )

    # Candidates: nov/2026 -> out/2026 -> set/2026 (second fallback succeeds).
    assert calls == [(2026, 11), (2026, 10), (2026, 9)]
    np.testing.assert_array_equal(values.astype(int), [[1, 1], [1, 1]])
    assert (target_year, target_month) == (2026, 9)


def test_t2g_biomass_array_returns_none_after_all_fallbacks(monkeypatch):
    from domain.services.geospatial import gee

    calls = []

    def empty_image(*args, **kwargs):
        calls.append((args[1], args[2]))
        return None

    grid = RasterGrid(
        crs="EPSG:4326",
        transform=(1.0, 0.0, 0.0, 0.0, -1.0, 1.0),
        width=2,
        height=2,
        scale=1,
    )
    monkeypatch.setattr(gee, "_get_t2g_biomass_image", empty_image)
    monkeypatch.setattr(gee, "dataset_exists", lambda *args, **kwargs: False)

    result = gee._get_t2g_biomass_array(
        roi="roi", feature_key="feature", month=1, year=2026, grid=grid,
        max_fallbacks=3,
    )

    assert result is None
    assert calls == [(2026, 1), (2025, 12), (2025, 11), (2025, 10)]


def test_resolve_gpw_biomass_year_falls_back_to_the_latest_year(monkeypatch):
    from domain.services.geospatial import pasture_biomass

    monkeypatch.setattr(pasture_biomass, "_latest_gpw_year", lambda: 2024)
    monkeypatch.setattr(
        pasture_biomass, "_gpw_year_available", lambda year: year == 2022
    )

    assert pasture_biomass.resolve_gpw_biomass_year(2022) == 2022
    assert pasture_biomass.resolve_gpw_biomass_year(2021) == 2024
    assert pasture_biomass.resolve_gpw_biomass_year(None) == 2024
    assert pasture_biomass.resolve_gpw_biomass_year(1999) == 2024
    assert pasture_biomass.resolve_gpw_biomass_year(2025) == 2024


def test_format_tick_uses_two_decimals_by_default():
    from domain.services.geospatial.image import format_tick

    assert format_tick(1.23456) == "1.23"
    assert format_tick(0) == "0.00"
    assert format_tick(12.3456, 1) == "12.3"


def _square(left: float, top: float, size: float):
    return [
        [left, top],
        [left + size, top],
        [left + size, top - size],
        [left, top - size],
        [left, top],
    ]


def test_roi_mask_marks_only_inside_the_polygon():
    from domain.services.geospatial.raster_render import roi_mask

    grid = RasterGrid(
        crs="EPSG:4326",
        transform=(0.01, 0.0, -51.0, 0.0, -0.01, -15.0),
        width=10,
        height=10,
        scale=1,
    )
    mask = roi_mask([_square(-51.0, -15.0, 0.05)], grid)

    assert mask.shape == (10, 10)
    assert mask[2, 2]
    # Left half only: the right side stays outside the property.
    assert not mask[2, 7]
    assert not mask[7, 7]


def test_roi_mask_handles_multipolygon_and_holes():
    from domain.services.geospatial.raster_render import roi_mask

    grid = RasterGrid(
        crs="EPSG:4326",
        transform=(0.01, 0.0, -51.0, 0.0, -0.01, -15.0),
        width=10,
        height=10,
        scale=1,
    )
    # MultiPolygon: two separate squares on the left and right halves.
    multi = roi_mask(
        [
            [_square(-51.0, -15.0, 0.04)],
            [_square(-50.96, -15.0, 0.04)],
        ],
        grid,
    )
    assert multi[1, 1] and multi[1, 6]

    # Polygon with a hole: the whole grid minus the left half.
    holed = roi_mask(
        [_square(-51.0, -15.0, 0.10), _square(-51.0, -15.0, 0.05)],
        grid,
    )
    assert not holed[2, 2]
    assert holed[2, 7]


def test_render_rgba_frame_clips_overlay_to_roi():
    from domain.services.geospatial.raster_render import render_rgba_frame

    grid = RasterGrid(
        crs="EPSG:4326",
        transform=(0.01, 0.0, -51.0, 0.0, -0.01, -15.0),
        width=10,
        height=10,
        scale=1,
    )
    base = np.zeros((10, 10, 3), dtype=np.uint8)
    overlay = np.zeros((10, 10, 4), dtype=np.uint8)
    overlay[..., 0] = 255
    overlay[..., 3] = 255

    image = render_rgba_frame(
        base, None, overlay, [_square(-51.0, -15.0, 0.05)], grid, dimension=10
    )

    assert image.size == (10, 10)
    assert image.getpixel((2, 2)) == (255, 0, 0)
    assert image.getpixel((7, 7)) == (0, 0, 0)
    assert image.getpixel((2, 7)) == (0, 0, 0)


def test_render_rgba_frame_upscales_small_grids_to_the_minimum():
    from domain.services.geospatial.raster_render import (
        MIN_RENDER_DIMENSION,
        render_rgba_frame,
    )

    grid = RasterGrid(
        crs="EPSG:4326",
        transform=(0.01, 0.0, -51.0, 0.0, -0.01, -15.0),
        width=5,
        height=4,
        scale=1,
    )
    base = np.zeros((4, 5, 3), dtype=np.uint8)
    overlay = np.zeros((4, 5, 4), dtype=np.uint8)

    image = render_rgba_frame(
        base, None, overlay, [_square(-51.0, -15.0, 0.05)], grid, dimension=None
    )

    assert max(image.size) == MIN_RENDER_DIMENSION
    assert image.size == (MIN_RENDER_DIMENSION, round(MIN_RENDER_DIMENSION * 4 / 5))


def test_render_rgba_frame_keeps_native_size_above_the_minimum():
    from domain.services.geospatial.raster_render import render_rgba_frame

    grid = RasterGrid(
        crs="EPSG:4326",
        transform=(0.01, 0.0, -51.0, 0.0, -0.01, -15.0),
        width=600,
        height=480,
        scale=1,
    )
    base = np.zeros((480, 600, 3), dtype=np.uint8)
    overlay = np.zeros((480, 600, 4), dtype=np.uint8)

    image = render_rgba_frame(
        base, None, overlay, [_square(-51.0, -15.0, 0.05)], grid, dimension=None
    )

    assert image.size == (600, 480)


def test_clean_mask_removes_salt_and_pinholes():
    from domain.services.geospatial.raster_render import clean_mask

    mask = np.zeros((40, 40), dtype=np.int16)
    mask[10:30, 10:30] = 1

    # Salt: isolated false positives. Pepper: single-pixel holes in a field.
    mask[2, 2] = 1
    mask[35, 35] = 1
    mask[15, 15] = 0
    mask[22, 18] = 0

    cleaned = clean_mask(mask)

    assert not cleaned[2, 2]
    assert not cleaned[35, 35]
    assert cleaned[15, 15]
    assert cleaned[22, 18]
    # The real field is untouched (minus its 1-px rounded corners).
    assert cleaned[12:28, 12:28].all()
    assert 380 <= int(cleaned.sum()) <= 400


def test_clean_mask_fills_larger_enclosed_holes():
    from domain.services.geospatial.raster_render import clean_mask

    mask = np.zeros((40, 40), dtype=np.int16)
    mask[5:35, 5:35] = 1
    mask[16:24, 16:24] = 0  # 8x8 hole fully enclosed by the field

    cleaned = clean_mask(mask)

    assert cleaned[16:24, 16:24].all()
    assert cleaned[7:33, 7:33].all()


def test_robust_range_ignores_the_outlier_tail():
    from domain.services.geospatial.raster_render import robust_range

    values = np.concatenate([np.linspace(0.0, 1.0, 1000), [1_000_000.0]])
    values = np.append(values, np.nan)

    vmin, vmax = robust_range(values)

    assert vmin == pytest.approx(0.02, abs=0.02)
    assert vmax < 1.0


def test_robust_range_falls_back_for_empty_input():
    from domain.services.geospatial.raster_render import robust_range

    assert robust_range(np.array([np.nan, np.nan])) == (0.0, 1.0)



def test_get_pasture_mask_array_cleans_and_caches_the_download(monkeypatch):
    from domain.services.geospatial import pasture_mask

    values = np.zeros((20, 20), dtype=np.int16)
    values[5:15, 5:15] = 1
    values[7, 7] = 0    # pinhole inside the field
    values[18, 18] = 1  # isolated false positive

    dataset = xr.Dataset(
        {"pasto": (("time", "y", "x"), values[np.newaxis, :, :])},
        coords={
            "time": [np.datetime64("2000-01-01")],
            "y": np.arange(20)[::-1] + 0.5,
            "x": np.arange(20) + 0.5,
        },
    )

    class _FakeImage:
        def gte(self, _value):
            return self

        def rename(self, _name):
            return self

    saved = {}

    monkeypatch.setattr(pasture_mask, "dataset_exists", lambda *a, **k: False)
    monkeypatch.setattr(pasture_mask, "_cached_pasture_array", lambda *a, **k: None)
    monkeypatch.setattr(pasture_mask, "_classify", lambda **k: (_FakeImage(), None))
    monkeypatch.setattr(
        pasture_mask, "download_image_dataset", lambda *a, **k: dataset.copy(deep=True)
    )
    monkeypatch.setattr(
        pasture_mask,
        "save_dataset",
        lambda car_code, key, ds, kind=None: saved.update(ds=ds, kind=kind),
    )

    grid = RasterGrid(
        crs="EPSG:4326",
        transform=(1.0, 0.0, 0.0, 0.0, -1.0, 20.0),
        width=20,
        height=20,
        scale=1,
    )
    result = pasture_mask.get_pasture_mask_array(
        roi="roi", feature_key="f", pred_year=2024, train_year=2023, grid=grid
    )

    assert result[7, 7]
    assert not result[18, 18]
    assert saved["kind"] == "pasture_mask"
    assert saved["ds"].attrs["cleaned"] is True
    assert saved["ds"]["pasto"].values[0][7, 7] == 1
    assert saved["ds"]["pasto"].values[0][18, 18] == 0


def test_colorbar_omits_the_mid_tick_on_narrow_images():
    from domain.services.geospatial.image import _colorbar_layout

    labels = ("16.12", "22.61", "29.10 ton/ha/ano")
    _, _, show_mid, width = _colorbar_layout(
        "assets/fonts/DejaVuSans-Bold.ttf", 12, labels, available=194, min_width=150
    )

    assert show_mid is False
    assert width <= 194


def test_colorbar_keeps_the_mid_tick_on_wide_images():
    from domain.services.geospatial.image import _colorbar_layout

    labels = ("16.12", "22.61", "29.10 ton/ha/ano")
    _, _, show_mid, width = _colorbar_layout(
        "assets/fonts/DejaVuSans-Bold.ttf", 12, labels, available=492, min_width=307
    )

    assert show_mid is True
    assert width == 307


def test_append_continuous_colorbar_fits_a_narrow_image():
    from PIL import Image

    from domain.services.geospatial.image import append_continuous_colorbar

    image = Image.new("RGB", (214, 217), "grey")
    out = append_continuous_colorbar(
        image, "Biomassa\n(2024) - GPW", 16.12, 29.10, "ton/ha/ano",
        ["#f75639", "#eef79c", "#f5d570", "#8aa637", "#0b391f"],
    )

    assert out.size[0] == 214
    assert out.size[1] > 217
