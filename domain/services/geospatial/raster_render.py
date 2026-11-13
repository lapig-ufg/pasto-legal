"""Local raster rendering helpers.

All GEE layers are cached as zarr arrays and composed into PNGs here, using
the same canonical grid, so a pasture mask and a biomass layer can be combined
pixel-by-pixel without any server-side Earth Engine operation.
"""

import math
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np
import PIL.Image
import PIL.ImageDraw
from pyproj import Transformer

from domain.services.geospatial.image import append_continuous_colorbar, append_discrete_legend
from domain.services.geospatial.xee_grid import RasterGrid


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


def resize_map(
    image: PIL.Image.Image,
    dimension: int,
    resampling: PIL.Image.Resampling = PIL.Image.Resampling.LANCZOS,
) -> PIL.Image.Image:
    """Resizes an image preserving aspect ratio, longest side = ``dimension``."""
    width, height = image.size
    if width <= 0 or height <= 0:
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
    dimension: int = 512,
    outline_width: int = 3,
    resampling: PIL.Image.Resampling = PIL.Image.Resampling.LANCZOS,
) -> PIL.Image.Image:
    """Composites a base RGB array with an RGBA overlay and resizes it."""
    composed = composite_rgba(base_rgb, overlay)
    image = PIL.Image.fromarray(composed, mode="RGB")
    image = resize_map(image, dimension, resampling=resampling)
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
    dimension: int = 512,
    ndigits: int | None = None,
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
    dimension: int = 512,
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


def _fit_dimension(width: float, height: float, dimension: int) -> Tuple[int, int]:
    if width <= 0 or height <= 0:
        return dimension, dimension
    if width >= height:
        return dimension, max(1, int(math.floor(dimension * height / width)))
    return max(1, int(math.floor(dimension * width / height))), dimension
