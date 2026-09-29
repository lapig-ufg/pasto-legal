"""Construction of the registration ``Feature`` objects from a GeoJSON geometry.

The user-facing intake formats (shapefile .zip/.rar, KMZ, KML, GeoJSON) are
converted to a single GeoJSON ``FeatureCollection`` by the framework's input
step (``semente.services.geospatial.geojson_io.convert_geo_file_to_geojson``);
this module only builds the domain ``Feature`` objects from that GeoJSON.

Kept free of Earth Engine dependencies so it can be unit-tested hermetically.

External interface:
    build_features_from_geojson  -- GeoJSON to (rural_property, paddocks)
    GeoFileError                 -- user-facing conversion failure
"""

import json
from typing import List, Union

import geopandas as gpd
import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from semente.logging import log_warning

from domain.schemas.feature import Feature

_HECTARES_PER_SQUARE_METER = 1.0 / 10_000.0
_WGS84_EPSG = 4326


class GeoFileError(ValueError):
    """Raised when a supported file cannot be converted to a usable GeoJSON."""


def _polygon_parts(geometry) -> List[Polygon]:
    """Recursively extracts the polygonal parts of a shapely geometry."""
    if geometry is None or geometry.is_empty:
        return []

    geom_type = geometry.geom_type
    if geom_type == "Polygon":
        return [geometry]
    if geom_type == "MultiPolygon":
        return list(geometry.geoms)
    if geom_type == "GeometryCollection":
        parts: List[Polygon] = []
        for sub_geometry in geometry.geoms:
            parts.extend(_polygon_parts(sub_geometry))
        return parts
    return []


def _safe_polygons(geometry) -> List[Polygon]:
    """Returns the polygonal parts of ``geometry``, repairing invalid shapes.

    Repair is applied to each part individually. Calling ``make_valid`` on a
    whole MultiPolygon whose parts overlap (a common case for adjacent
    paddocks) would merge them into a single geometry and lose the paddock
    boundaries, so every part is validated on its own.
    """
    try:
        if geometry is None or geometry.is_empty:
            return []

        parts: List[Polygon] = []
        for part in _polygon_parts(geometry):
            if part.is_valid:
                parts.append(part)
                continue
            try:
                parts.extend(_polygon_parts(shapely.make_valid(part)))
            except Exception as error:  # pragma: no cover - defensive
                log_warning(f"geojson_io: invalid geometry skipped ({error})")
        return parts
    except Exception as error:  # pragma: no cover - defensive
        log_warning(f"geojson_io: invalid geometry skipped ({error})")
        return []


def _geometry_to_coords(geometry) -> List[List[List[List[float]]]]:
    """Converts a shapely (Multi)Polygon to the schema GeoJSON coordinate nesting."""

    def rings(polygon: Polygon) -> List[List[List[float]]]:
        result = [[[float(x), float(y)] for x, y in polygon.exterior.coords]]
        for interior in polygon.interiors:
            result.append([[float(x), float(y)] for x, y in interior.coords])
        return result

    if geometry.geom_type == "Polygon":
        return [rings(geometry)]
    return [rings(part) for part in geometry.geoms]


def _area_hectares(geometry) -> float:
    """Computes the area in hectares using a local UTM projection."""
    series = gpd.GeoSeries([geometry], crs=f"EPSG:{_WGS84_EPSG}")
    projected = series.to_crs(series.estimate_utm_crs())
    return round(float(projected.area.iloc[0]) * _HECTARES_PER_SQUARE_METER, 2)


def _extract_geometry(geojson: Union[bytes, str, dict]):
    """Extracts a shapely (Multi)Polygon from a GeoJSON payload."""
    if isinstance(geojson, (bytes, bytearray)):
        try:
            geojson = geojson.decode("utf-8")
        except UnicodeDecodeError as error:
            raise GeoFileError("O arquivo GeoJSON não está em UTF-8.") from error

    if isinstance(geojson, str):
        try:
            geojson = json.loads(geojson)
        except json.JSONDecodeError as error:
            raise GeoFileError(
                "O conteúdo GeoJSON recebido é inválido. "
                "Passe o conteúdo exato do arquivo enviado pelo usuário."
            ) from error

    if not isinstance(geojson, dict):
        raise GeoFileError("O conteúdo GeoJSON recebido é inválido.")

    geometries = []
    if geojson.get("type") == "FeatureCollection":
        geojson_features = geojson.get("features") or []
        geometries = [f.get("geometry") for f in geojson_features if isinstance(f, dict)]
    elif geojson.get("type") == "Feature":
        geometries = [geojson.get("geometry")]
    elif geojson.get("type") in ("Polygon", "MultiPolygon"):
        geometries = [geojson]

    polygons: List[Polygon] = []
    for geometry in geometries:
        if not geometry:
            continue
        try:
            polygons.extend(_safe_polygons(shapely.geometry.shape(geometry)))
        except Exception as error:
            log_warning(f"geojson_io: invalid GeoJSON geometry skipped ({error})")

    if not polygons:
        raise GeoFileError(
            "Nenhum polígono válido foi encontrado no GeoJSON recebido. "
            "Passe o conteúdo exato do arquivo enviado pelo usuário."
        )

    if len(polygons) == 1:
        return polygons[0]
    return MultiPolygon(polygons)


def build_features_from_geojson(
    geojson: Union[bytes, str, dict],
) -> tuple[Feature, List[Feature]]:
    """Builds the rural property (and paddocks) from a GeoJSON geometry.

    A single polygon becomes one ``rural_property``. Several polygons become one
    ``paddock`` per polygon (ids ``Paddock_1..N``) plus one ``rural_property``
    that is the dissolve of all of them. Paddocks and property start with
    independent ids; the property id is a generated base id.

    Args:
        geojson: GeoJSON bytes, string or parsed mapping.

    Returns:
        Tuple ``(rural_property, paddocks)``; ``paddocks`` is empty for a single
        polygon.

    Raises:
        GeoFileError: When no polygon is present.
    """
    geometry = _extract_geometry(geojson)

    if geometry.geom_type == "Polygon":
        property_feature = Feature(
            feature_id=Feature.generate_id(),
            coords=_geometry_to_coords(geometry),
            metadata=[],
            total_area=_area_hectares(geometry),
            region=None,
            feature_type="rural_property",
        )
        return property_feature, []

    parts = list(geometry.geoms)
    paddocks = [
        Feature(
            feature_id=f"Paddock_{index}",
            coords=_geometry_to_coords(part),
            metadata=[],
            total_area=_area_hectares(part),
            region=None,
            feature_type="paddock",
        )
        for index, part in enumerate(parts, start=1)
    ]

    dissolved = unary_union(parts)
    property_feature = Feature(
        feature_id=Feature.generate_id(),
        coords=_geometry_to_coords(dissolved),
        metadata=[],
        total_area=_area_hectares(dissolved),
        region=None,
        feature_type="rural_property",
    )

    return property_feature, paddocks