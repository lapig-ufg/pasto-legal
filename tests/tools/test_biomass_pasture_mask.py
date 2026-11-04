"""
Máscara de pastagem on-the-fly da biomassa Time2Graze (sem Earth Engine real).

    .venv/bin/python -m pytest tests/tools/test_biomass_pasture_mask.py -v
"""
from domain.schemas.feature import Feature
from domain.services.geospatial import pasture_classification
from domain.tools import analysis_tools


class _FakeClassified:
    def gte(self, value):
        return ("mask", value)


def test_mask_is_the_binarized_classification_with_the_map_default_years(monkeypatch):
    calls = []
    monkeypatch.setattr(pasture_classification, "_latest_mapbiomas_year", lambda: 2023)
    monkeypatch.setattr(
        pasture_classification, "_classify",
        lambda roi, train_year, pred_year: calls.append((train_year, pred_year)) or (_FakeClassified(), None),
    )

    assert pasture_classification.get_on_the_fly_pasture_mask(roi="roi") == ("mask", 1)
    assert calls == [(2023, 2024)]


def test_mask_is_none_when_the_classification_is_unavailable(monkeypatch):
    def unavailable(roi, train_year, pred_year):
        raise ValueError("Satellite Embedding not yet available")

    monkeypatch.setattr(pasture_classification, "_latest_mapbiomas_year", lambda: 2023)
    monkeypatch.setattr(pasture_classification, "_classify", unavailable)

    assert pasture_classification.get_on_the_fly_pasture_mask(roi="roi") is None


def test_tool_helper_builds_the_mask_from_the_property_geometry(monkeypatch):
    received = []
    monkeypatch.setattr(analysis_tools.ee.Geometry, "MultiPolygon", lambda coords: ("geometry", coords))
    monkeypatch.setattr(analysis_tools, "get_on_the_fly_pasture_mask", lambda roi: received.append(roi) or "mask")
    coords = [[[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]]]
    feature = Feature(feature_id="CAR-1", coords=coords, metadata=[], total_area=1.0, feature_type="rural_property")

    assert analysis_tools._biomass_pasture_mask(feature) == "mask"
    assert received == [("geometry", coords)]
