"""Local raster rendering helpers.

All GEE layers are cached as zarr arrays and composed into PNGs here, using
the same canonical grid, so a pasture mask and a biomass layer can be combined
pixel-by-pixel without any server-side Earth Engine operation.
"""

from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np
import PIL.Image
import PIL.ImageDraw
import PIL.ImageFilter
import PIL.ImageOps
from pyproj import Transformer

from domain.services.geospatial.image import append_continuous_colorbar, append_discrete_legend
from domain.services.geospatial.xee_grid import RasterGrid

# Native-resolution renders are clamped to this window so small properties stay
# readable and huge ones stay manageable. Any resampling here is nearest
# neighbour (never LANCZOS), which would blur the raster cells.
MIN_RENDER_DIMENSION = 512
MAX_RENDER_DIMENSION = 4096

# Single ramp for every biomass layer (T2G map, GPW fallback and the video), so
# the same quantity never changes colour between products.
BIOMASS_PALETTE = ["#f75639", "#eef79c", "#f5d570", "#8aa637", "#0b391f"]


def _rgb(hex_color: str) -> Tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def continuous_rgba(
    values: np.ndarray,
    palette: Sequence[str],
    vmin: float,
    vmax: float,
) -> np.ndarray:
    """Maps a continuous 2-D array to an RGBA image using a colour ramp."""
    values = np.asarray(values, dtype=np.float64)
    height, width = values.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)

    valid = np.isfinite(values)
    if not valid.any():
        return rgba

    if vmax <= vmin:
        vmax = vmin + 1e-9

    normalized = np.clip((values - vmin) / (vmax - vmin), 0.0, 1.0)
    normalized = np.nan_to_num(normalized, nan=0.0)
    colors = np.array([_rgb(color) for color in palette], dtype=np.float64)
    positions = np.linspace(0.0, 1.0, len(colors))

    for channel in range(3):
        rgba[..., channel] = np.interp(
            normalized, positions, colors[:, channel]
        ).astype(np.uint8)

    rgba[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
    return rgba


def discrete_rgba(
    values: np.ndarray,
    class_colors: Dict[int, str],
) -> np.ndarray:
    """Maps integer class values to an RGBA image."""
    values = np.asarray(values)
    height, width = values.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)

    for class_value, color in class_colors.items():
        mask = values == class_value
        if not mask.any():
            continue
        rgba[mask] = (*_rgb(color), 255)

    return rgba


def composite_rgba(base_rgb: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    """Alpha-blends an RGBA overlay over an RGB base."""
    base = np.asarray(base_rgb, dtype=np.float64)
    if base.ndim != 3 or base.shape[2] < 3:
        raise ValueError("base_rgb must have shape (height, width, 3).")
    if base.shape[:2] != overlay.shape[:2]:
        raise ValueError("base and overlay grids do not match.")

    alpha = overlay[..., 3:4].astype(np.float64) / 255.0
    overlay_rgb = overlay[..., :3].astype(np.float64)
    blended = base[..., :3] * (1.0 - alpha) + overlay_rgb * alpha
    return np.clip(blended, 0, 255).astype(np.uint8)


def _project_ring(ring: Iterable[Sequence[float]], grid: RasterGrid) -> List[Tuple[float, float]]:
    transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    lons = [point[0] for point in ring]
    lats = [point[1] for point in ring]
    xs, ys = transformer.transform(lons, lats)

    a, _b, c, _d, e, f = grid.transform
    columns = (np.asarray(xs) - c) / a - 0.5
    rows = (np.asarray(ys) - f) / e - 0.5
    return list(zip(columns.tolist(), rows.tolist()))


def _iter_polygons(coords):
    """Yields polygons from either Polygon or MultiPolygon coordinate nesting.

    Earth Engine simplifies a single-polygon MultiPolygon back to a Polygon, so
    ``geometry.coordinates().getInfo()`` may return either:
        Polygon:      [ring, ...]
        MultiPolygon: [[ring, ...], ...]
    """
    if not coords:
        return

    probe = coords[0]
    if not probe or not probe[0]:
        return

    # Polygon: coords[0][0] is a point ([x, y]), so its first element is numeric.
    if isinstance(probe[0][0], (int, float)):
        yield coords
        return

    yield from coords


def draw_outline(
    image: PIL.Image.Image,
    coords,
    grid: RasterGrid,
    color: Tuple[int, int, int] = (255, 0, 0),
    width: int = 3,
) -> PIL.Image.Image:
    """Draws a property outline on ``image`` using the grid affine.

    Accepts both GeoJSON Polygon and MultiPolygon coordinate nestings.
    """
    draw = PIL.ImageDraw.Draw(image)
    for polygon in _iter_polygons(coords):
        for ring in polygon:
            points = _project_ring(ring, grid)
            if len(points) < 2:
                continue
            draw.line(points, fill=color, width=width, joint="curve")
            draw.line([points[-1], points[0]], fill=color, width=width)
    return image


def roi_mask(coords, grid: RasterGrid) -> np.ndarray:
    """Boolean mask of the property polygon(s) on the raster grid.

    Accepts both Polygon and MultiPolygon coordinate nestings, and excludes
    interior rings (holes). Returns an all-True mask when there are no
    coordinates, so a malformed geometry never silently drops a whole layer.
    """
    if not coords:
        return np.ones((grid.height, grid.width), dtype=bool)

    mask = PIL.Image.new("L", (int(grid.width), int(grid.height)), 0)
    draw = PIL.ImageDraw.Draw(mask)

    for polygon in _iter_polygons(coords):
        if not polygon:
            continue
        exterior = _project_ring(polygon[0], grid)
        if len(exterior) >= 3:
            draw.polygon(exterior, fill=255)
        for hole in polygon[1:]:
            hole_points = _project_ring(hole, grid)
            if len(hole_points) >= 3:
                draw.polygon(hole_points, fill=0)

    mask_array = np.asarray(mask, dtype=np.uint8) > 0
    if not mask_array.any():
        # Degenerate geometry (e.g. an unexpected nesting): keep the whole
        # layer visible rather than silently rendering an empty map.
        return np.ones((grid.height, grid.width), dtype=bool)
    return mask_array


def fill_mask_holes(mask: np.ndarray) -> np.ndarray:
    """Fills holes fully enclosed by a boolean 2-D mask.

    Uses a flood fill from a one-pixel padded border on the inverted mask: any
    background region still set after the fill is enclosed and therefore a hole.
    """
    mask = np.asarray(mask, dtype=bool)
    inverted = PIL.Image.fromarray((~mask).astype(np.uint8) * 255)
    inverted = PIL.ImageOps.expand(inverted, border=1, fill=255)
    PIL.ImageDraw.floodfill(inverted, (0, 0), 0)
    inverted = inverted.crop((1, 1, inverted.width - 1, inverted.height - 1))
    return mask | (np.asarray(inverted) > 127)


def clean_mask(
    values: np.ndarray,
    median_size: int = 3,
    closing_size: int = 5,
) -> np.ndarray:
    """Cleans a binary raster mask (1 = mapped class) for display.

    The per-pixel classifications are speckled at 10 m: isolated false
    positives, pinholes inside fields and stair-stepped edges. At native
    resolution that reads as confetti, so the mask is regularised with:

    1. a median filter (removes single-pixel salt/pepper),
    2. a morphological closing (fills pinholes and small notches),
    3. hole filling (removes larger fully enclosed gaps).

    Large fields and their real boundaries are preserved.
    """
    mask = np.asarray(values) == 1
    if mask.size == 0:
        return mask

    image = PIL.Image.fromarray(mask.astype(np.uint8) * 255)
    image = image.filter(PIL.ImageFilter.MedianFilter(median_size))
    image = image.filter(PIL.ImageFilter.MaxFilter(closing_size))
    image = image.filter(PIL.ImageFilter.MinFilter(closing_size))

    return fill_mask_holes(np.asarray(image) > 127)


def robust_range(
    values: np.ndarray,
    lower: float = 2.0,
    upper: float = 98.0,
) -> Tuple[float, float]:
    """Percentile display range, robust to the long tail of raster outliers.

    Using absolute min/max on a skewed layer (e.g. biomass: median 0.29 with a
    max of 1.08) squeezes almost every pixel into two shades of the ramp.
    """
    values = np.asarray(values, dtype=np.float64)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0

    vmin = float(np.percentile(finite, lower))
    vmax = float(np.percentile(finite, upper))
    if vmax <= vmin:
        vmax = vmin + 1e-9
    return vmin, vmax


def resize_map(
    image: PIL.Image.Image,
    dimension: int | None,
    resampling: PIL.Image.Resampling = PIL.Image.Resampling.LANCZOS,
) -> PIL.Image.Image:
    """Resizes an image preserving aspect ratio, longest side = ``dimension``.

    ``dimension=None`` keeps the native pixel size (one image pixel per raster
    cell), which is what the biomass maps use so no pixel is ever blurred.
    """
    width, height = image.size
    if width <= 0 or height <= 0 or dimension is None:
        return image
    if width >= height:
        new_size = (dimension, max(1, round(dimension * height / width)))
    else:
        new_size = (max(1, round(dimension * width / height)), dimension)
    return image.resize(new_size, resampling)


def grid_for_image_size(grid: RasterGrid, size: Tuple[int, int]) -> RasterGrid:
    """Returns a grid whose pixel space matches an already-resized image."""
    width, height = size
    a, b, c, d, e, f = grid.transform
    # The image has more/fewer pixels than the source grid, so its pixel size
    # must shrink/grow by the inverse scale factor.
    scale_x = grid.width / width
    scale_y = grid.height / height
    return RasterGrid(
        crs=grid.crs,
        transform=(
            a * scale_x,
            b,
            c,
            d,
            e * scale_y,
            f,
        ),
        width=int(width),
        height=int(height),
        scale=grid.scale,
    )


def render_rgba_frame(
    base_rgb: np.ndarray,
    values: np.ndarray,
    overlay: np.ndarray,
    coords: List[List[List[List[float]]]],
    grid: RasterGrid,
    dimension: int | None = 512,
    outline_width: int = 3,
    resampling: PIL.Image.Resampling = PIL.Image.Resampling.LANCZOS,
    clip_to_roi: bool = True,
) -> PIL.Image.Image:
    """Composites a base RGB array with an RGBA overlay and resizes it.

    The overlay is clipped to the property polygon before compositing, so data
    never paints outside the farm while the satellite image stays as the full
    background. Masking happens before the composite, keeping the result opaque
    and avoiding transparent halos when the image is resized.

    ``dimension=None`` keeps the native grid resolution, clamped to
    ``[MIN_RENDER_DIMENSION, MAX_RENDER_DIMENSION]`` with nearest-neighbour
    resampling: small properties stay readable without ever being blurred.
    """
    if clip_to_roi:
        mask = roi_mask(coords, grid)
        if mask.any():
            overlay = overlay.copy()
            overlay[..., 3] = np.where(mask, overlay[..., 3], 0)

    composed = composite_rgba(base_rgb, overlay)
    image = PIL.Image.fromarray(composed, mode="RGB")

    if dimension is not None:
        image = resize_map(image, dimension, resampling=resampling)
    else:
        # Native resolution, clamped so tiny properties are still readable.
        longest = max(image.size)
        target = min(max(longest, MIN_RENDER_DIMENSION), MAX_RENDER_DIMENSION)
        if target != longest:
            image = resize_map(
                image, target, resampling=PIL.Image.Resampling.NEAREST
            )

    return draw_outline(
        image,
        coords,
        grid_for_image_size(grid, image.size),
        width=outline_width,
    )


def render_continuous_map(
    base_rgb: np.ndarray,
    values: np.ndarray,
    coords: List[List[List[List[float]]]],
    grid: RasterGrid,
    palette: Sequence[str],
    title: str,
    unit: str,
    vmin: float,
    vmax: float,
    dimension: int | None = 512,
    ndigits: int = 2,
) -> PIL.Image.Image:
    """Renders a continuous layer over a cached satellite base, with colorbar."""
    overlay = continuous_rgba(values, palette, vmin, vmax)
    image = render_rgba_frame(base_rgb, values, overlay, coords, grid, dimension=dimension)
    return append_continuous_colorbar(
        image,
        title=title,
        vmin=vmin,
        vmax=vmax,
        unit=unit,
        palette=list(palette),
        ndigits=ndigits,
    )


def render_discrete_map(
    base_rgb: np.ndarray,
    values: np.ndarray,
    coords: List[List[List[List[float]]]],
    grid: RasterGrid,
    class_colors: Dict[int, str],
    class_labels: Dict[int, str],
    title: str,
    dimension: int | None = 512,
) -> PIL.Image.Image:
    """Renders a discrete layer over a cached satellite base, with legend."""
    overlay = discrete_rgba(values, class_colors)
    image = render_rgba_frame(
        base_rgb,
        values,
        overlay,
        coords,
        grid,
        dimension=dimension,
        resampling=PIL.Image.Resampling.NEAREST,
    )
    legend = {class_labels[key]: class_colors[key] for key in class_labels if key in class_colors}
    return append_discrete_legend(image, title, legend)


def resize_nearest(values: np.ndarray, target_shape: Tuple[int, int]) -> np.ndarray:
    """Nearest-neighbour resize for 2-D masks (used when grids differ)."""
    height, width = target_shape
    rows = (np.arange(height) * values.shape[0] / height).astype(int)
    cols = (np.arange(width) * values.shape[1] / width).astype(int)
    rows = np.clip(rows, 0, values.shape[0] - 1)
    cols = np.clip(cols, 0, values.shape[1] - 1)
    return values[np.ix_(rows, cols)]
