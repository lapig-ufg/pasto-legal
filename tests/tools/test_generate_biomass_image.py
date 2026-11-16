"""
Testes da tool `generate_biomass_image`: período opcional, fallback de até quatro
meses no T2G e fallback anual do GPW (com o ano mais recente quando o pedido não
existe no GPW).

`domain/tools/analysis_tools.py` importa `gee.py`, que inicializa o Earth Engine
na importação do módulo — então este teste precisa de um `.env` real na raiz do
projeto (GEE_PROJECT, GEE_SERVICE_ACCOUNT, GEE_KEY_FILE), mesma ressalva de
tests/tools/test_cache_key_for.py.

    .venv/bin/python -m pytest tests/tools/test_generate_biomass_image.py -v
"""
import datetime

import PIL

from domain.schemas.feature import Feature, FeatureMetadata
from domain.tools import analysis_tools


class _FixedDate(datetime.date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 16)


def _property() -> Feature:
    return Feature(
        feature_id="GO-5211800-987B29E7E47A4454BAEF582557AB89F3",
        coords=[[[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]]],
        metadata=[FeatureMetadata(key="car_code", value="GO-5211800-987B29E7E47A4454BAEF582557AB89F3")],
        total_area=1.0,
        feature_type="rural_property",
    )


def _image() -> PIL.Image.Image:
    return PIL.Image.new("RGB", (4, 4))


def _patch_property(monkeypatch):
    monkeypatch.setattr(analysis_tools, "resolve_feature", lambda *args, **kwargs: _property())


def test_uses_current_month_and_year_when_period_is_omitted(monkeypatch):
    _patch_property(monkeypatch)
    monkeypatch.setattr(analysis_tools.datetime, "date", _FixedDate)

    calls = []

    def fake_retrieve(coords, month, year, **kwargs):
        calls.append((month, year))
        return _image(), year, month

    monkeypatch.setattr(analysis_tools, "retrieve_t2g_biomass_image", fake_retrieve)

    result = analysis_tools.generate_biomass_image(run_context=None, feature_id="feature")

    assert calls == [(11, 2026)]
    assert "Não havia dados" not in result.content


def test_passes_the_requested_month_and_year(monkeypatch):
    _patch_property(monkeypatch)

    calls = []

    def fake_retrieve(coords, month, year, **kwargs):
        calls.append((month, year))
        return _image(), year, month

    monkeypatch.setattr(analysis_tools, "retrieve_t2g_biomass_image", fake_retrieve)

    result = analysis_tools.generate_biomass_image(
        run_context=None, feature_id="feature", month=8, year=2025
    )

    assert calls == [(8, 2025)]
    assert "mês 8, ano 2025" in result.content
    assert "Não havia dados" not in result.content


def test_reports_when_t2g_used_an_older_month(monkeypatch):
    _patch_property(monkeypatch)
    monkeypatch.setattr(
        analysis_tools,
        "retrieve_t2g_biomass_image",
        lambda *args, **kwargs: (_image(), 2025, 6),
    )

    result = analysis_tools.generate_biomass_image(
        run_context=None, feature_id="feature", month=8, year=2025
    )

    assert "mês 6, ano 2025" in result.content
    assert "8/2025" in result.content
    assert "Não havia dados" in result.content


def test_rejects_a_future_period_without_calling_the_service(monkeypatch):
    _patch_property(monkeypatch)
    monkeypatch.setattr(analysis_tools.datetime, "date", _FixedDate)
    monkeypatch.setattr(
        analysis_tools,
        "retrieve_t2g_biomass_image",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not call")),
    )

    result = analysis_tools.generate_biomass_image(
        run_context=None, feature_id="feature", month=12, year=2026
    )

    assert "futuro" in result.content


def test_rejects_an_invalid_month_without_calling_the_service(monkeypatch):
    _patch_property(monkeypatch)
    monkeypatch.setattr(
        analysis_tools,
        "retrieve_t2g_biomass_image",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not call")),
    )

    result = analysis_tools.generate_biomass_image(
        run_context=None, feature_id="feature", month=13, year=2025
    )

    assert "entre 1 (janeiro) e 12 (dezembro)" in result.content


def test_gpw_fallback_uses_the_requested_year_and_reports_the_effective_one(monkeypatch):
    _patch_property(monkeypatch)
    monkeypatch.setattr(
        analysis_tools, "retrieve_t2g_biomass_image", lambda *args, **kwargs: None
    )

    calls = []

    def fake_gpw(coords, year=None, feature_key=None):
        calls.append(year)
        return _image(), 2024

    monkeypatch.setattr(analysis_tools, "retrieve_gpw_biomass_image", fake_gpw)

    result = analysis_tools.generate_biomass_image(
        run_context=None, feature_id="feature", month=3, year=2020
    )

    assert calls == [2020]
    assert "ano 2024" in result.content
