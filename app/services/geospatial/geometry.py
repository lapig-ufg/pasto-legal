from typing import Tuple

from pyproj import CRS, Transformer
from shapely.geometry import Point
from shapely.ops import transform as shapely_transform

from agno.utils.log import log_error

from app.schemas.property_feature import SpatialFeatures
from app.schemas.property_feature import BufferedArea

# Earth circumference divisor used to locate the UTM zone for a longitude.
_UTM_ZONE_WIDTH_DEG = 6.0
_WGS84_EPSG = 4326
_SOUTHERN_HEMISPHERE_EPSG_OFFSET = 32700
_NORTHERN_HEMISPHERE_EPSG_OFFSET = 32600
_BUFFER_QUADRANT_SEGMENTS = 32
_HECTARES_PER_SQUARE_METER = 1.0 / 10_000.0


def _utm_epsg_for(latitude: float, longitude: float) -> int:
    """
    Returns the EPSG code of the local UTM projection for a coordinate,
    ensuring metric units for buffer and area computation.
    """
    zone = int((longitude + 180.0) // _UTM_ZONE_WIDTH_DEG) + 1
    offset = (
        _SOUTHERN_HEMISPHERE_EPSG_OFFSET
        if latitude < 0
        else _NORTHERN_HEMISPHERE_EPSG_OFFSET
    )
    return offset + zone


def create_buffer_polygon(
    latitude: float,
    longitude: float,
    radius: float,
) -> Tuple[Tuple[float, float], list]:
    """
    Creates a circular buffer (in meters) around a geographic coordinate.

    The point is projected to the local UTM CRS so the radius is applied in
    true meters, then the polygon is reprojected back to WGS84 (GeoJSON
    lon/lat pairs).

    Args:
        latitude (float): Latitude in decimal degrees.
        longitude (float): Longitude in decimal degrees.
        radius (float): Buffer radius in meters.

    Returns:
        Tuple containing:
            - (latitude, longitude) of the buffer center.
            - GeoJSON MultiPolygon nested coordinates of the buffer polygon.
            - Buffer area in hectares (computed in the metric UTM space).
    """
    try:
        geographic_crs = CRS.from_epsg(_WGS84_EPSG)
        projected_crs = CRS.from_epsg(_utm_epsg_for(latitude, longitude))

        to_utm = Transformer.from_crs(geographic_crs, projected_crs, always_xy=True)
        to_wgs84 = Transformer.from_crs(projected_crs, geographic_crs, always_xy=True)

        point = Point(longitude, latitude)
        point_utm = shapely_transform(to_utm.transform, point)

        if point_utm.is_empty:
            raise ValueError("Coordinate could not be projected to UTM.")

        buffered_utm = point_utm.buffer(radius, quad_segs=_BUFFER_QUADRANT_SEGMENTS)

        if not buffered_utm.is_valid or buffered_utm.is_empty:
            raise ValueError("Buffer generation produced an invalid polygon.")

        area_ha = buffered_utm.area * _HECTARES_PER_SQUARE_METER

        buffered_wgs84 = shapely_transform(to_wgs84.transform, buffered_utm)
        buffered_wgs84 = buffered_wgs84.simplify(1e-9, preserve_topology=True)

        exterior = list(buffered_wgs84.exterior.coords)
        polygon_ring = [[float(x), float(y)] for x, y in exterior]
        coordinates = [[polygon_ring]]

        return (latitude, longitude), coordinates, area_ha
    except Exception as e:
        log_error(f"create_buffer_polygon: {e}")
        raise


def build_buffered_area(
    latitude: float,
    longitude: float,
    radius: float,
) -> BufferedArea:
    """
    Builds a BufferedArea schema from a coordinate and a radius in meters.

    Computes the buffer polygon in UTM, derives its area in hectares and
    packages everything into the BufferedArea model.
    """
    center, coordinates, total_area_ha = create_buffer_polygon(
        latitude=latitude,
        longitude=longitude,
        radius=radius,
    )

    return BufferedArea(
        radius=radius,
        center=center,
        spatial_features=SpatialFeatures(
            total_area=round(total_area_ha, 2),
            coordinates=coordinates,
        ),
    )