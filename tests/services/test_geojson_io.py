"""
Testes herméticos da conversão de arquivos geoespaciais para GeoJSON e da
construção das feições de registro (sem GEE, sem credenciais).

    PYTHONPATH=. uv run pytest tests/services/test_geojson_io.py -v
"""
import json
import os
import tempfile
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from app.services.geospatial.geojson_io import (
    GeoFileError,
    build_features_from_geojson,
    convert_geo_file_to_geojson,
    save_debug_json,
)


def _single_polygon_geojson() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
                },
            }
        ],
    }


def _multi_polygon_geojson() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
                        [[[2, 2], [2, 3], [3, 3], [3, 2], [2, 2]]],
                    ],
                },
            }
        ],
    }


_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>P1</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
-49.2,-16.6,0 -49.1,-16.6,0 -49.1,-16.5,0 -49.2,-16.5,0 -49.2,-16.6,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>P2</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
-49.0,-16.6,0 -48.9,-16.6,0 -48.9,-16.5,0 -49.0,-16.5,0 -49.0,-16.6,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
</Document></kml>"""


def test_geojson_passthrough_single_polygon():
    raw = json.dumps(_single_polygon_geojson()).encode()

    converted = convert_geo_file_to_geojson(raw, "property.geojson")
    parsed = json.loads(converted)

    assert parsed["type"] == "FeatureCollection"
    assert parsed["features"][0]["geometry"]["type"] == "Polygon"


def test_multi_polygon_becomes_multipolygon_geometry():
    raw = json.dumps(_multi_polygon_geojson()).encode()

    parsed = json.loads(convert_geo_file_to_geojson(raw, "property.json"))

    assert parsed["features"][0]["geometry"]["type"] == "MultiPolygon"


def test_kml_conversion_collects_all_placemarks():
    parsed = json.loads(convert_geo_file_to_geojson(_KML.encode(), "map.kml"))

    geometry = parsed["features"][0]["geometry"]
    assert geometry["type"] == "MultiPolygon"
    assert len(geometry["coordinates"]) == 2


def test_kmz_conversion():
    with tempfile.TemporaryDirectory() as tmp:
        kml_path = os.path.join(tmp, "doc.kml")
        with open(kml_path, "w") as file:
            file.write(_KML)
        kmz_path = os.path.join(tmp, "map.kmz")
        with zipfile.ZipFile(kmz_path, "w") as archive:
            archive.write(kml_path, "doc.kml")

        content = open(kmz_path, "rb").read()

    parsed = json.loads(convert_geo_file_to_geojson(content, "map.kmz"))
    assert parsed["features"][0]["geometry"]["type"] == "MultiPolygon"


def test_zipped_shapefile_conversion():
    with tempfile.TemporaryDirectory() as tmp:
        gdf = gpd.GeoDataFrame(
            {"name": ["p1"]},
            geometry=[Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])],
            crs="EPSG:4326",
        )
        gdf.to_file(os.path.join(tmp, "layer.shp"))

        zip_path = os.path.join(tmp, "shape.zip")
        with zipfile.ZipFile(zip_path, "w") as archive:
            for name in os.listdir(tmp):
                if name.endswith((".shp", ".shx", ".dbf", ".prj", ".cpg")):
                    archive.write(os.path.join(tmp, name), name)

        content = open(zip_path, "rb").read()

    parsed = json.loads(convert_geo_file_to_geojson(content, "shape.zip"))
    assert parsed["features"][0]["geometry"]["type"] == "Polygon"


def test_unsupported_extension_raises_geofile_error():
    with pytest.raises(GeoFileError):
        convert_geo_file_to_geojson(b"anything", "notes.txt")


def test_file_without_polygon_raises_geofile_error():
    point_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            }
        ],
    }
    with pytest.raises(GeoFileError):
        convert_geo_file_to_geojson(
            json.dumps(point_collection).encode(), "points.geojson"
        )


def test_build_features_single_polygon_returns_only_property():
    raw = json.dumps(_single_polygon_geojson()).encode()

    property_feature, paddocks = build_features_from_geojson(raw)

    assert property_feature.feature_type == "rural_property"
    assert property_feature.total_area > 0
    assert paddocks == []


def test_build_features_multi_polygon_returns_paddocks_and_dissolved_property():
    raw = json.dumps(_multi_polygon_geojson()).encode()

    property_feature, paddocks = build_features_from_geojson(raw)

    assert property_feature.feature_type == "rural_property"
    assert [paddock.feature_id for paddock in paddocks] == ["Paddock_1", "Paddock_2"]
    assert all(paddock.feature_type == "paddock" for paddock in paddocks)
    # The property is the dissolve of every paddock.
    assert property_feature.total_area == pytest.approx(
        sum(paddock.total_area for paddock in paddocks), rel=1e-6
    )


def test_build_features_accepts_geojson_string():
    property_feature, paddocks = build_features_from_geojson(
        json.dumps(_single_polygon_geojson())
    )

    assert property_feature.feature_type == "rural_property"
    assert paddocks == []


def test_build_features_invalid_json_raises_geofile_error():
    with pytest.raises(GeoFileError):
        build_features_from_geojson("{not json")


def test_overlapping_parts_are_not_merged_into_one_geometry():
    """Adjacent/overlapping paddocks must stay as separate features.

    Regression: calling make_valid on the whole MultiPolygon merged the parts
    into a single invalid shape, dropping the paddock boundaries (85 -> 5).
    """
    overlapping = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]],
                        [[[5, 5], [5, 15], [15, 15], [15, 5], [5, 5]]],
                        [[[20, 20], [20, 30], [30, 30], [30, 20], [20, 20]]],
                    ],
                },
            }
        ],
    }

    property_feature, paddocks = build_features_from_geojson(json.dumps(overlapping))

    # Every original part must survive as its own paddock.
    assert [paddock.feature_id for paddock in paddocks] == [
        "Paddock_1",
        "Paddock_2",
        "Paddock_3",
    ]
    # The property is the dissolve: the two overlapping parts merge, so it
    # ends up with 2 parts instead of the 3 original paddocks.
    assert len(property_feature.coords) == 2


def test_polygon_with_hole_keeps_its_interior_ring():
    polygon_with_hole = {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]],
            [[2, 2], [2, 4], [4, 4], [4, 2], [2, 2]],
        ],
    }

    property_feature, paddocks = build_features_from_geojson(polygon_with_hole)

    assert paddocks == []
    # One polygon with an exterior ring and one interior (hole) ring.
    assert len(property_feature.coords) == 1
    assert len(property_feature.coords[0]) == 2


def test_save_debug_json_disabled_outside_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")

    assert save_debug_json(b'{"type": "FeatureCollection"}', "x") is None


def test_save_debug_json_writes_file_in_development(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(
        "app.services.geospatial.geojson_io._DEBUG_DIR", tmp_path / "geojson_debug"
    )

    path = save_debug_json(b'{"type": "FeatureCollection"}', "input_step_converted_x")

    assert path is not None and path.exists()
    assert path.suffix == ".json"
    assert "input_step_converted_x" in path.name
    assert json.loads(path.read_text())["type"] == "FeatureCollection"


def test_save_debug_json_accepts_dict(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(
        "app.services.geospatial.geojson_io._DEBUG_DIR", tmp_path / "geojson_debug"
    )

    path = save_debug_json(_multi_polygon_geojson(), "tool")

    assert path is not None and path.exists()
