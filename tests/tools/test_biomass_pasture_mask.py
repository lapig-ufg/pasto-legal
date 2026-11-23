"""
Máscara de pastagem da biomassa Time2Graze (sem Earth Engine real).

    .venv/bin/python -m pytest tests/tools/test_biomass_pasture_mask.py -v
"""
from domain.services.geospatial import pasture_classification


class _FakeClassified:
    def gte(self, value):
        return ("mask", value)


def test_mask_is_the_binarized_classification_with_the_map_default_years(monkeypatch):
    calls = []
    monkeypatch.setattr(pasture_classification, "latest_classification_year", lambda: 2023)
    monkeypatch.setattr(
        pasture_classification, "_classify",
        lambda roi, train_year, pred_year: calls.append((train_year, pred_year)) or (_FakeClassified(), None),
    )

    assert pasture_classification.get_pasture_mask_image(roi="roi") == ("mask", 1)
    assert calls == [(2023, 2024)]


def test_classification_cache_reuses_the_same_property_year(monkeypatch):
    calls = []
    pasture_classification.clear_classify_cache()
    monkeypatch.setattr(
        pasture_classification, "_classify",
        lambda **kwargs: calls.append(kwargs) or ("classified", "embedding"),
    )

    first = pasture_classification._classify_cached(
        roi="roi", car_code="CAR-1", train_year=2023, pred_year=2024
    )
    second = pasture_classification._classify_cached(
        roi="roi", car_code="CAR-1", train_year=2023, pred_year=2024
    )

    assert first == second
    assert len(calls) == 1


def test_mask_falls_back_to_the_static_map_when_classification_is_unavailable(monkeypatch):
    def unavailable(roi, train_year, pred_year):
        raise ValueError("Satellite Embedding not yet available")

    monkeypatch.setattr(pasture_classification, "latest_classification_year", lambda: 2023)
    monkeypatch.setattr(pasture_classification, "_classify", unavailable)
    monkeypatch.setattr(
        pasture_classification, "_static_pasture_image",
        lambda roi, year: ("static", year),
    )

    assert pasture_classification.get_pasture_mask_image(roi="roi") == ("static", 2023)


def test_mask_is_none_when_both_sources_are_unavailable(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ValueError("unavailable")

    monkeypatch.setattr(pasture_classification, "latest_classification_year", lambda: 2023)
    monkeypatch.setattr(pasture_classification, "_classify", unavailable)
    monkeypatch.setattr(pasture_classification, "_static_pasture_image", unavailable)

    assert pasture_classification.get_pasture_mask_image(roi="roi") is None
