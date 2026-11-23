"""Fallback and composition tests for the pasture analyses.

    .venv/bin/python -m pytest tests/tools/test_pasture_fallbacks.py -v
"""
from domain.schemas.feature import Feature, FeatureMetadata
from domain.schemas.property_stats import (
    AgeData,
    AgeStats,
    BiomassStats,
    LULCData,
    LULCStats,
    Value,
    VigorData,
    VigorStats,
)
from domain.services.geospatial import pasture_age, pasture_vigor
from domain.services.geospatial.pasture_age import AgeAnalysis
from domain.services.geospatial.pasture_vigor import VigorAnalysis
from domain.tools import analysis_tools


def _age_stats() -> AgeStats:
    return AgeStats(
        observation_year=2024,
        data=[AgeData(age="1-10", amount=Value(value=12.0, unity="hectares (ha)"))],
    )


def _vigor_stats() -> VigorStats:
    return VigorStats(
        observation_year=2024,
        data=[VigorData(vigor="Alto", amount=Value(value=7.0, unity="hectares (ha)"))],
    )


class _FakeRoi:
    def coordinates(self):
        return self

    def getInfo(self):
        return "coords"


def test_analyze_pasture_age_falls_back_to_static(monkeypatch):
    monkeypatch.setattr(
        pasture_age,
        "estimate_pasture_age",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("embedding unavailable")),
    )
    monkeypatch.setattr(pasture_age, "get_pasture_age", lambda **kwargs: _age_stats())
    monkeypatch.setattr(pasture_age, "latest_asset_year", lambda *args, **kwargs: 2024)
    monkeypatch.setattr(pasture_age, "_render_static_age_image", lambda **kwargs: "static-map")

    result = pasture_age.analyze_pasture_age(roi="roi", car_code="CAR-1")

    assert result.source == "mapbiomas"
    assert result.pred_year == 2024
    assert result.stats is not None
    assert result.image == "static-map"


def test_analyze_pasture_age_does_not_call_static_when_estimate_succeeds(monkeypatch):
    monkeypatch.setattr(
        pasture_age,
        "estimate_pasture_age",
        lambda **kwargs: AgeAnalysis(
            stats=_age_stats(), image="estimated-map", pred_year=2025,
            train_year=2024, source="on_the_fly",
        ),
    )
    monkeypatch.setattr(
        pasture_age,
        "get_pasture_age",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not use static")),
    )

    result = pasture_age.analyze_pasture_age(roi="roi", car_code="CAR-1")

    assert result.source == "on_the_fly"
    assert result.image == "estimated-map"


def test_analyze_pasture_vigor_falls_back_to_static(monkeypatch):
    monkeypatch.setattr(
        pasture_vigor,
        "estimate_pasture_vigor",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("embedding unavailable")),
    )
    monkeypatch.setattr(pasture_vigor, "get_pasture_vigor", lambda **kwargs: _vigor_stats())
    monkeypatch.setattr(pasture_vigor, "latest_asset_year", lambda *args, **kwargs: 2024)
    monkeypatch.setattr(
        pasture_vigor, "retrieve_pasture_vigor_image", lambda **kwargs: "static-map"
    )

    result = pasture_vigor.analyze_pasture_vigor(roi=_FakeRoi(), car_code="CAR-1")

    assert result.source == "mapbiomas"
    assert result.pred_year == 2024
    assert result.stats is not None
    assert result.image == "static-map"


def _property() -> Feature:
    return Feature(
        feature_id="CAR-1",
        coords=[[[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]]],
        metadata=[FeatureMetadata(key="car_code", value="CAR-1")],
        total_area=1.0,
        feature_type="rural_property",
    )


def test_get_pasture_stats_composes_the_individual_analyses(monkeypatch):
    monkeypatch.setattr(analysis_tools, "resolve_feature", lambda *args, **kwargs: _property())
    monkeypatch.setattr(analysis_tools.ee.Geometry, "MultiPolygon", lambda coords: "roi")
    monkeypatch.setattr(
        analysis_tools,
        "get_biomass",
        lambda *args, **kwargs: BiomassStats(
            observation_year=2025,
            period="mensal",
            amount=Value(value=10.0, unity="toneladas"),
        ),
    )
    monkeypatch.setattr(
        analysis_tools,
        "analyze_pasture_age",
        lambda **kwargs: AgeAnalysis(
            stats=_age_stats(), image=None, pred_year=2024,
            train_year=None, source="mapbiomas",
        ),
    )
    monkeypatch.setattr(
        analysis_tools,
        "analyze_pasture_vigor",
        lambda **kwargs: VigorAnalysis(
            stats=_vigor_stats(), image=None, pred_year=2024,
            train_year=None, source="mapbiomas",
        ),
    )
    monkeypatch.setattr(
        analysis_tools,
        "get_land_use_land_cover",
        lambda *args, **kwargs: LULCStats(
            observation_year=2024,
            data=[LULCData(lulc_class="Pastagem", amount=Value(value=9.0, unity="hectares"))],
        ),
    )

    result = analysis_tools.get_pasture_stats(run_context=None, feature_id="CAR-1")

    assert "Biomassa" in result.content
    assert "idade" in result.content.lower()
    assert "vigor" in result.content.lower()
    assert "LULC" in result.content
