"""
Testes herméticos das conversões de unidade e do tratamento de datas (sem GEE).

Cobre os requisitos 1 (conversão conhecida com pixel sintético), 3 (janeiro,
virada de ano e mês incompleto) e 10 (reprodutibilidade da chave de cache).

    PYTHONPATH=. .venv/bin/python -m pytest tests/biomass/test_biomass_conversions.py -v
"""
import datetime

import pytest

from app.services.geospatial.biomass.biomass_productivity import (
    annual_period,
    daily_rate_to_dry_matter_t_ha,
    dry_matter_conversion_factors,
    is_partial_month,
    monthly_period,
    uncertainty_bounds,
)
from app.services.geospatial.biomass.biomass_validation import (
    CARBON_TO_DRY_MATTER,
    GRAMS_PER_M2_TO_TONS_PER_HA,
    GRASS_LUE_MAX_GC_PER_MJ,
    MAPBIOMAS_PASTURE_BIOMASS_CONTRACT,
    T2G_UGPP_CONTRACT,
    build_cache_key,
    geometry_signature,
    get_contract,
)


_SQUARE = [[[[-50.6, -16.3], [-50.6, -16.2], [-50.5, -16.2], [-50.5, -16.3], [-50.6, -16.3]]]]


# -----------------------------------------------------------------------------
# Requisito 1: conversão de unidades com pixel sintético
# -----------------------------------------------------------------------------

def test_synthetic_pixel_converts_to_known_dry_matter():
    """
    Pixel sintético com DN bruto conhecido, verificado passo a passo.

    DN 1000 x escala 0,01 = 10 MJ/m²/dia de APAR
        x LUE 0,50 gC/MJ  = 5 gC/m²/dia
        x IPCC 2,7        = 13,5 g MS/m²/dia
        x 30 dias         = 405 g MS/m²
        x 0,01            = 4,05 t MS/ha
    """
    result = daily_rate_to_dry_matter_t_ha(mean_daily_dn=1000.0, days=30)

    assert result == pytest.approx(4.05, abs=1e-9)


def test_conversion_is_linear_in_days_and_in_signal():
    assert daily_rate_to_dry_matter_t_ha(500.0, 30) == pytest.approx(
        daily_rate_to_dry_matter_t_ha(1000.0, 30) / 2
    )
    assert daily_rate_to_dry_matter_t_ha(1000.0, 15) == pytest.approx(
        daily_rate_to_dry_matter_t_ha(1000.0, 30) / 2
    )


def test_zero_signal_converts_to_zero_dry_matter():
    assert daily_rate_to_dry_matter_t_ha(0.0, 31) == 0.0


def test_conversion_factors_are_all_named_and_sourced():
    """Requisito: nenhum fator sem fonte documentada."""
    factors = dry_matter_conversion_factors()

    assert set(factors) == {
        "asset_scale", "grass_fraction_or_lue", "carbon_to_dry_matter", "unit_conversion",
    }
    assert factors["asset_scale"] == T2G_UGPP_CONTRACT.stored_scale
    assert factors["grass_fraction_or_lue"] == GRASS_LUE_MAX_GC_PER_MJ
    assert factors["carbon_to_dry_matter"] == CARBON_TO_DRY_MATTER
    assert factors["unit_conversion"] == GRAMS_PER_M2_TO_TONS_PER_HA


def test_t2g_asset_scale_is_the_validated_one():
    """
    Regressão da correção de escala.

    A escala 0,1 produzia ~145 t MS/ha/ano no imóvel de teste contra 21 t MS/ha/ano
    do MapBiomas, e implicava uma APAR de 63,8 MJ/m²/dia — mais de 3x a radiação
    solar incidente em Goiás. A evidência está registrada no contrato do asset.
    """
    assert T2G_UGPP_CONTRACT.stored_scale == 0.01
    assert T2G_UGPP_CONTRACT.evidence, "o contrato precisa registrar a evidência da escala"
    assert T2G_UGPP_CONTRACT.verification_status in ("inferred", "documented")


def test_mapbiomas_values_need_no_scaling():
    """Os valores de pixel do MapBiomas já estão em t MS/ha/ano."""
    assert MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.stored_scale == 1.0
    assert MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.native_unit == "t MS/ha/ano"


def test_unknown_asset_has_no_conversion_factors():
    with pytest.raises(Exception, match="não tem contrato"):
        get_contract("projects/algum/asset/inexistente")


def test_uncertainty_bounds_bracket_the_central_value():
    lower, upper = uncertainty_bounds(4.05)

    assert lower < 4.05 < upper
    assert lower == pytest.approx(4.05 * 0.40 / 0.50)
    assert upper == pytest.approx(4.05 * 0.65 / 0.50)


def test_uncertainty_bounds_of_missing_value_are_missing():
    assert uncertainty_bounds(None) == (None, None)


# -----------------------------------------------------------------------------
# Requisito 3: janeiro, virada de ano e mês incompleto
# -----------------------------------------------------------------------------

def test_january_period_spans_the_whole_month():
    start, end = monthly_period(2026, 1, today=datetime.date(2026, 6, 15))

    assert start == datetime.date(2026, 1, 1)
    assert end == datetime.date(2026, 2, 1)
    assert (end - start).days == 31


def test_december_period_rolls_into_the_next_year():
    start, end = monthly_period(2025, 12, today=datetime.date(2026, 6, 15))

    assert start == datetime.date(2025, 12, 1)
    assert end == datetime.date(2026, 1, 1)
    assert (end - start).days == 31


def test_february_of_a_leap_year_has_twenty_nine_days():
    start, end = monthly_period(2028, 2, today=datetime.date(2028, 6, 1))

    assert (end - start).days == 29


def test_current_month_is_truncated_at_today():
    """Mês incompleto: o período devolvido é o observável, não o mês inteiro."""
    start, end = monthly_period(2026, 9, today=datetime.date(2026, 9, 21))

    assert start == datetime.date(2026, 9, 1)
    assert end == datetime.date(2026, 9, 21)
    assert (end - start).days == 20
    assert is_partial_month(start, end) is True


def test_complete_past_month_is_not_flagged_as_partial():
    start, end = monthly_period(2026, 8, today=datetime.date(2026, 9, 21))

    assert is_partial_month(start, end) is False


def test_future_month_has_no_observable_period():
    with pytest.raises(ValueError, match="ainda não começou"):
        monthly_period(2027, 3, today=datetime.date(2026, 9, 21))


def test_month_outside_range_is_rejected():
    for month in (0, 13):
        with pytest.raises(ValueError, match="entre 1"):
            monthly_period(2026, month, today=datetime.date(2026, 9, 21))


def test_annual_period_spans_the_calendar_year():
    start, end = annual_period(2024)

    assert start == datetime.date(2024, 1, 1)
    assert end == datetime.date(2025, 1, 1)
    assert (end - start).days == 366


# -----------------------------------------------------------------------------
# Requisito 10: reprodutibilidade da chave de cache
# -----------------------------------------------------------------------------

def _key(**overrides) -> str:
    kwargs = dict(
        metric_type="monthly_dry_matter_productivity",
        coords=_SQUARE,
        period_start=datetime.date(2026, 8, 1),
        period_end=datetime.date(2026, 9, 1),
        model_version="monthly-productivity-v1",
        conversion_factors=dry_matter_conversion_factors(),
        mask_signature="Global Pasture Watch|ggc-30m v1-1|2024|30|official",
    )
    kwargs.update(overrides)
    return build_cache_key(**kwargs)


def test_cache_key_is_deterministic():
    assert _key() == _key()


def test_cache_key_changes_with_geometry():
    other = [[[[-50.7, -16.3], [-50.7, -16.2], [-50.6, -16.2], [-50.6, -16.3], [-50.7, -16.3]]]]

    assert _key() != _key(coords=other)


def test_cache_key_changes_with_conversion_factors():
    """Mudar um fator invalida o cache em vez de servir o número antigo."""
    wrong_scale = dry_matter_conversion_factors()
    wrong_scale["asset_scale"] = 0.1

    assert _key() != _key(conversion_factors=wrong_scale)


def test_cache_key_changes_with_model_version():
    assert _key() != _key(model_version="monthly-productivity-v2")


def test_cache_key_changes_with_period_and_mask():
    assert _key() != _key(period_start=datetime.date(2026, 7, 1))
    assert _key() != _key(mask_signature="Global Pasture Watch|ggc-30m v1-1|2023|30|official")


def test_cache_key_is_insensitive_to_factor_ordering():
    factors = dry_matter_conversion_factors()
    reordered = {key: factors[key] for key in reversed(list(factors))}

    assert _key(conversion_factors=factors) == _key(conversion_factors=reordered)


def test_cache_key_is_namespaced_by_metric():
    key = _key()

    assert key.startswith("monthly_dry_matter_productivity:")
    assert _key(metric_type="annual_dry_matter_productivity") != key


def test_geometry_signature_is_stable_across_runs():
    assert geometry_signature(_SQUARE) == geometry_signature(_SQUARE)
    assert len(geometry_signature(_SQUARE)) == 16
