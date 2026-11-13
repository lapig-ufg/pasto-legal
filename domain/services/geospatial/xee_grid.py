import hashlib
import json
from dataclasses import dataclass
from typing import Optional, Tuple

import affine
import ee
import numpy as np
from pyproj import Transformer


def _utm_grid(roi: ee.Geometry, crs: str, scale: int) -> Tuple[affine.Affine, int, int]:
    """
    Calcula a grade de pixels do bbox do imóvel projetado no CRS alvo.

    A API do Xee (0.1.1) exige a grade explícita (crs_transform + shape_2d) em
    vez de scale/geometry, por isso derivamos o transform affine e as dimensões.

    Args:
        roi (ee.Geometry): Geometria do imóvel.
        crs (str): CRS métrico alvo (ex.: "EPSG:32722").
        scale (int): Tamanho do pixel em metros.

    Returns:
        Tuple[affine.Affine, int, int]: transform, largura (x) e altura (y) em pixels.
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


def _native_crs(image: ee.Image) -> str:
    """Retorna o CRS nativo (métrico) da imagem."""
    return image.select(0).projection().getInfo()["crs"]


def _utm_crs_for_roi(roi: ee.Geometry) -> str:
    """Deriva o EPSG UTM métrico a partir do centroide do imóvel."""
    lon, lat = roi.centroid(1).coordinates().getInfo()
    zone = int((lon + 180) // 6) + 1
    hemisphere_base = 32700 if lat < 0 else 32600
    return f"EPSG:{hemisphere_base + zone}"


@dataclass(frozen=True)
class RasterGrid:
    """Grade raster canônica compartilhada por todas as camadas de um imóvel.

    Todas as camadas (satélite, pastagem, biomassa, idade, vigor, solo) precisam
    usar exatamente o mesmo CRS/transform/dimensões para que máscaras e overlays
    possam ser combinados localmente, sem reprojeção no momento do render.
    """

    crs: str
    transform: Tuple[float, float, float, float, float, float]
    width: int
    height: int
    scale: int

    @property
    def affine(self) -> affine.Affine:
        return affine.Affine(*self.transform)

    @property
    def hash(self) -> str:
        payload = json.dumps(
            {
                "crs": self.crs,
                "transform": [round(value, 6) for value in self.transform],
                "width": self.width,
                "height": self.height,
                "scale": self.scale,
            },
            sort_keys=True,
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def grid_for_roi(roi: ee.Geometry, scale: int = 10, buffer_m: int = 0) -> RasterGrid:
    """Builds the canonical grid for a property.

    The grid covers the property bounding box plus ``buffer_m`` (the same buffer
    used by the rendered maps), in the UTM zone of the property centroid.
    """
    crs = _utm_crs_for_roi(roi)
    projection = ee.Projection(crs)
    region = roi.buffer(buffer_m).bounds(1) if buffer_m else roi.bounds(1)
    ring = ee.List(region.transform(projection, 1).coordinates().get(0)).getInfo()

    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]

    x_min = (min(xs) // scale) * scale
    x_max = -(-max(xs) // scale) * scale
    y_min = (min(ys) // scale) * scale
    y_max = -(-max(ys) // scale) * scale

    width = max(1, round((x_max - x_min) / scale))
    height = max(1, round((y_max - y_min) / scale))
    transform = (scale, 0.0, x_min, 0.0, -scale, y_max)

    return RasterGrid(
        crs=crs,
        transform=transform,
        width=width,
        height=height,
        scale=scale,
    )


def source_grid_from_dataset(dataset, band_name: Optional[str] = None) -> RasterGrid:
    """Reconstructs the raster grid of a zarr/xee dataset from its coordinates."""
    var = dataset[band_name] if band_name else next(iter(dataset.data_vars.values()))
    crs = var.attrs.get("crs") or dataset.attrs.get("crs")
    if not crs:
        raise ValueError("Dataset has no CRS attribute.")

    x = np.asarray(dataset["x"].values)
    y = np.asarray(dataset["y"].values)
    if x.size < 2 or y.size < 2:
        raise ValueError("Dataset has fewer than two pixels on an axis.")

    dx = float(x[1] - x[0])
    dy = float(y[1] - y[0])
    x0 = float(x[0] - dx / 2)
    y0 = float(y[0] - dy / 2)
    scale = int(round(abs(dx)))

    return RasterGrid(
        crs=str(crs),
        transform=(dx, 0.0, x0, 0.0, dy, y0),
        width=int(x.size),
        height=int(y.size),
        scale=scale,
    )


def resample_nearest(values: np.ndarray, source: RasterGrid, target: RasterGrid) -> np.ndarray:
    """Resamples a 2-D array onto ``target`` using nearest-neighbour indexing."""
    if values.ndim != 2:
        raise ValueError("resample_nearest expects a 2-D array.")
    if source.hash == target.hash and values.shape == (target.height, target.width):
        return values

    cols, rows = np.meshgrid(np.arange(target.width), np.arange(target.height))
    a, _b, c, _d, e, f = target.transform
    x = c + (cols + 0.5) * a
    y = f + (rows + 0.5) * e

    if source.crs != target.crs:
        transformer = Transformer.from_crs(target.crs, source.crs, always_xy=True)
        x, y = transformer.transform(x, y)

    src_a, _src_b, src_c, _src_d, src_e, src_f = source.transform
    src_cols = (x - src_c) / src_a - 0.5
    src_rows = (y - src_f) / src_e - 0.5
    src_cols = np.rint(src_cols).astype(int)
    src_rows = np.rint(src_rows).astype(int)

    valid = (
        (src_cols >= 0)
        & (src_cols < values.shape[1])
        & (src_rows >= 0)
        & (src_rows < values.shape[0])
    )

    output = np.full((target.height, target.width), np.nan, dtype=np.float64)
    output[valid] = values[src_rows[valid], src_cols[valid]]
    return output