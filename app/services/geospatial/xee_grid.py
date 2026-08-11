from typing import Tuple

import affine
import ee


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


def _native_crs(collection: ee.ImageCollection) -> str:
    """Retorna o CRS nativo (métrico) da primeira imagem da coleção."""
    return collection.first().select(0).projection().getInfo()["crs"]
