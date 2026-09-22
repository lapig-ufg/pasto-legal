"""
Testes da tool `start_registration_by_geojson` e do fluxo de nomeação de
piquetes em `complete_registration`.

`app/tools/property_tools.py` importa `gee.py`, que inicializa o Earth Engine
na importação do módulo — então este teste precisa de um `.env` real na raiz do
projeto (GEE_PROJECT, GEE_SERVICE_ACCOUNT, GEE_KEY_FILE), mesmo com o GEE
mockado. Mesma ressalva de tests/pdf/test_generate_property_boletim_tool.py.

    .venv/bin/python -m pytest tests/tools/test_start_registration_by_geojson.py -v
"""
import json

import PIL
import pytest
from agno.media import File
from agno.run import RunContext

from app.tools import property_tools


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


def _context() -> RunContext:
    return RunContext(run_id="test-run", session_id="test-session", session_state={})


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

    result = property_tools.start_registration_by_geojson.entrypoint(
        run_context=run_context, files=[_geojson_file(geojson)]
    )

    assert run_context.session_state["registration_state"] == "pending"
    assert len(run_context.session_state["candidate_properties"]) == 1
    assert run_context.session_state["pending_paddocks"] == []
    assert result.images
    assert result.images[0].content[:8] == b"\x89PNG\r\n\x1a\n"


def test_start_registration_by_geojson_multi_polygon_creates_paddocks(fake_overview_image):
    run_context = _context()

    result = property_tools.start_registration_by_geojson.entrypoint(
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

    result = property_tools.start_registration_by_geojson.entrypoint(
        run_context=run_context, files=[_geojson_file("{not json")]
    )

    assert run_context.session_state.get("registration_state") is None
    assert "candidate_properties" not in run_context.session_state
    assert not result.images
    assert result.content


def test_start_registration_by_geojson_without_file_returns_instruction(fake_overview_image):
    run_context = _context()

    result = property_tools.start_registration_by_geojson.entrypoint(
        run_context=run_context, files=None
    )

    assert run_context.session_state.get("registration_state") is None
    assert not result.images
    assert result.content


def test_complete_registration_renames_paddocks(fake_overview_image):
    run_context = _context()
    property_tools.start_registration_by_geojson.entrypoint(
        run_context=run_context, files=[_geojson_file(_multi_polygon_geojson())]
    )

    property_tools.complete_registration.entrypoint(
        run_context=run_context, name="Fazenda Primavera"
    )

    registered = run_context.session_state["all_properties"]["features"]
    registered_ids = [feature["feature_id"] for feature in registered]
    assert registered_ids == [
        "Fazenda Primavera",
        "Fazenda Primavera_1",
        "Fazenda Primavera_2",
    ]
    assert run_context.session_state["registration_state"] is None
    assert run_context.session_state["candidate_properties"] is None
    assert run_context.session_state["pending_paddocks"] is None


def test_cancel_registration_clears_pending_paddocks(fake_overview_image):
    run_context = _context()
    property_tools.start_registration_by_geojson.entrypoint(
        run_context=run_context, files=[_geojson_file(_multi_polygon_geojson())]
    )

    property_tools.cancel_registration.entrypoint(run_context=run_context)

    assert run_context.session_state["registration_state"] is None
    assert run_context.session_state["candidate_properties"] is None
    assert run_context.session_state["pending_paddocks"] is None


def test_paddock_centroid_supports_polygons_with_holes():
    """Regression: shapely's MultiPolygon(coords) ctor rejects GeoJSON nesting."""
    from app.services.geospatial.gee import _paddock_centroid

    coords = [
        [
            [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]],
            [[2, 2], [2, 4], [4, 4], [4, 2], [2, 2]],
        ]
    ]

    lat, lon = _paddock_centroid(coords)

    assert 0 <= lat <= 10
    assert 0 <= lon <= 10
