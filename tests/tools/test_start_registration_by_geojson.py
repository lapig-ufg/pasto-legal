"""
Testes da tool `start_registration_by_geojson` e do fluxo de nomeação de
piquetes em `complete_registration`.

`domain/tools/property_tools.py` importa `gee.py`, que inicializa o Earth Engine
na importação do módulo — então este teste precisa de um `.env` real na raiz do
projeto (GEE_PROJECT, GEE_SERVICE_ACCOUNT, GEE_KEY_FILE), mesmo com o GEE
mockado. Mesma ressalva de tests/pdf/test_generate_property_boletim_tool.py.

    .venv/bin/python -m pytest tests/tools/test_start_registration_by_geojson.py -v
"""
import json

import PIL
import pytest

from semente.backends.toolkit import StateContext
from semente.tools import File

from domain.tools import property_tools


def _multi_polygon_geojson() -> str:
    return json.dumps(
        {
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
    )


@pytest.fixture
def fake_overview_image(monkeypatch):
    """Replaces the GEE image generation with a tiny in-memory PNG."""
    def _fake(*args, **kwargs):
        return PIL.Image.new("RGB", (32, 32), "green")

    monkeypatch.setattr(
        property_tools, "retrieve_property_overview_image", _fake, raising=True
    )


def _context() -> StateContext:
    return StateContext(session_state={})


def _geojson_file(geojson: str) -> File:
    return File(
        content=geojson.encode(),
        mime_type="application/json",
        name="property.json",
        format="geojson",
    )


def test_start_registration_by_geojson_single_polygon(fake_overview_image):
    geojson = json.dumps(
        {
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
    )
    run_context = _context()

    result = property_tools.start_registration_by_geojson(
        run_context=run_context, files=[_geojson_file(geojson)]
    )

    assert run_context.session_state["registration_state"] == "pending"
    assert len(run_context.session_state["candidate_properties"]) == 1
    assert run_context.session_state["pending_paddocks"] == []
    assert result.images
    assert result.images[0].content[:8] == b"\x89PNG\r\n\x1a\n"


def test_start_registration_by_geojson_multi_polygon_creates_paddocks(fake_overview_image):
    run_context = _context()

    result = property_tools.start_registration_by_geojson(
        run_context=run_context, files=[_geojson_file(_multi_polygon_geojson())]
    )

    paddocks = run_context.session_state["pending_paddocks"]
    assert [p["feature_id"] for p in paddocks] == ["Paddock_1", "Paddock_2"]
    assert all(p["feature_type"] == "paddock" for p in paddocks)
    # Only the rural property is offered as the candidate to be named.
    assert len(run_context.session_state["candidate_properties"]) == 1
    assert run_context.session_state["candidate_properties"][0]["feature_type"] == "rural_property"
    assert result.images


def test_start_registration_by_geojson_invalid_content_returns_instruction(fake_overview_image):
    run_context = _context()

    result = property_tools.start_registration_by_geojson(
        run_context=run_context, files=[_geojson_file("{not json")]
    )

    assert run_context.session_state.get("registration_state") is None
    assert "candidate_properties" not in run_context.session_state
    assert not result.images
    assert result.content


def test_start_registration_by_geojson_without_file_returns_instruction(fake_overview_image):
    run_context = _context()

    result = property_tools.start_registration_by_geojson(
        run_context=run_context, files=None
    )

    assert run_context.session_state.get("registration_state") is None
    assert not result.images
    assert result.content


def test_complete_registration_names_paddocks(fake_overview_image):
    run_context = _context()
    property_tools.start_registration_by_geojson(
        run_context=run_context, files=[_geojson_file(_multi_polygon_geojson())]
    )

    property_tools.complete_registration(
        run_context=run_context, name="Fazenda Primavera"
    )

    registered = run_context.session_state["all_properties"]["features"]
    assert len(registered) == 3

    # feature_id stays stable; the display name lives in metadata.
    property_feature, *paddock_features = registered
    assert property_feature["feature_id"] != "Fazenda Primavera"
    paddock_ids = [feature["feature_id"] for feature in paddock_features]
    assert paddock_ids == ["Paddock_1", "Paddock_2"]

    property_names = [
        next(e["value"] for e in feature["metadata"] if e["key"] == "name")
        for feature in registered
    ]
    assert property_names == [
        "Fazenda Primavera",
        "Fazenda Primavera_1",
        "Fazenda Primavera_2",
    ]
    assert run_context.session_state["registration_state"] is None
    assert run_context.session_state["candidate_properties"] is None
    assert run_context.session_state["pending_paddocks"] is None


def test_cancel_registration_clears_pending_paddocks(fake_overview_image):
    run_context = _context()
    property_tools.start_registration_by_geojson(
        run_context=run_context, files=[_geojson_file(_multi_polygon_geojson())]
    )

    property_tools.cancel_registration(run_context=run_context)

    assert run_context.session_state["registration_state"] is None
    assert run_context.session_state["candidate_properties"] is None
    assert run_context.session_state["pending_paddocks"] is None


def test_paddock_centroid_supports_polygons_with_holes():
    """Regression: shapely's MultiPolygon(coords) ctor rejects GeoJSON nesting."""
    from domain.services.geospatial.gee import _paddock_centroid

    coords = [
        [
            [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]],
            [[2, 2], [2, 4], [4, 4], [4, 2], [2, 2]],
        ]
    ]

    lat, lon = _paddock_centroid(coords)

    assert 0 <= lat <= 10
    assert 0 <= lon <= 10


# ---------------------------------------------------------------------------
# Paddock names coming from the source file (polygon_labels)
# ---------------------------------------------------------------------------

def _labeled_geojson(labels: list, parts: int = None) -> str:
    """One MultiPolygon with one square per part, as the input step builds it."""
    parts = len(labels) if parts is None else parts
    squares = [
        [[[3 * i, 0], [3 * i, 1], [3 * i + 1, 1], [3 * i + 1, 0], [3 * i, 0]]]
        for i in range(parts)
    ]
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"polygon_labels": labels},
                    "geometry": {"type": "MultiPolygon", "coordinates": squares},
                }
            ],
        }
    )


def _registered_names(run_context) -> list:
    return [
        next((e["value"] for e in feature["metadata"] if e["key"] == "name"), None)
        for feature in run_context.session_state["all_properties"]["features"]
    ]


def test_paddocks_list_number_and_source_name(fake_overview_image):
    run_context = _context()

    result = property_tools.start_registration_by_geojson(
        run_context=run_context,
        files=[_geojson_file(_labeled_geojson(["Piquete A", "Piquete B"]))],
    )

    assert "1 = Piquete A, 2 = Piquete B" in result.content
    # The ids stay stable; the image keeps drawing the numbers.
    paddocks = run_context.session_state["pending_paddocks"]
    assert [p["feature_id"] for p in paddocks] == ["Paddock_1", "Paddock_2"]


def test_complete_registration_prefixes_the_farm_name(fake_overview_image):
    run_context = _context()
    property_tools.start_registration_by_geojson(
        run_context=run_context,
        files=[_geojson_file(_labeled_geojson(["Piquete A", None]))],
    )

    property_tools.complete_registration(run_context=run_context, name="Fazenda Um")

    assert _registered_names(run_context) == [
        "Fazenda Um",
        "Fazenda Um - Piquete A",
        "Fazenda Um_2",
    ]


def test_same_file_on_two_farms_keeps_names_unique(fake_overview_image):
    run_context = _context()
    for farm in ("Fazenda Um", "Fazenda Dois"):
        property_tools.start_registration_by_geojson(
            run_context=run_context,
            files=[_geojson_file(_labeled_geojson(["Piquete A"] * 2))],
        )
        property_tools.complete_registration(run_context=run_context, name=farm)

    names = _registered_names(run_context)
    assert len(names) == len(set(names))
    assert "Fazenda Dois - Piquete A (2)" in names


def test_repeated_names_in_one_file_are_numbered(fake_overview_image):
    run_context = _context()

    result = property_tools.start_registration_by_geojson(
        run_context=run_context,
        files=[_geojson_file(_labeled_geojson(["Pasto", "Pasto", "Sede"]))],
    )

    assert "1 = Pasto, 2 = Pasto (2), 3 = Sede" in result.content


def test_many_paddocks_show_only_the_total(fake_overview_image):
    run_context = _context()
    labels = [f"P{i}" for i in range(1, 13)]

    result = property_tools.start_registration_by_geojson(
        run_context=run_context, files=[_geojson_file(_labeled_geojson(labels))]
    )

    assert "Piquetes identificados: 12." in result.content
    assert "1 = P1" not in result.content


def test_labels_that_do_not_match_the_parts_are_ignored(fake_overview_image):
    run_context = _context()

    result = property_tools.start_registration_by_geojson(
        run_context=run_context,
        files=[_geojson_file(_labeled_geojson(["A", "B", "C"], parts=2))],
    )

    assert "Piquetes identificados: 1, 2" in result.content
