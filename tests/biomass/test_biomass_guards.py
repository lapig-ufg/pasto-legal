"""
Testes herméticos das guardas de coerência (sem GEE).

Cobre os requisitos 4 (dados faltantes e fallback explícito), 5 (proibição de
calcular UA com métrica mensal) e 6 (separação entre fonte mensal e anual).

    PYTHONPATH=. .venv/bin/python -m pytest tests/biomass/test_biomass_guards.py -v
"""
import datetime

import pytest

from app.schemas.biomass_schemas import BiomassEstimate
from app.services.geospatial.biomass.available_forage import (
    compute_available_forage_t_ha,
    default_parameters,
    estimate_available_forage,
)
from app.services.geospatial.biomass.biomass_productivity import annualize_monthly_series
from app.services.geospatial.biomass.biomass_validation import (
    AGRONOMIC_ENVELOPES,
    ImplausibleEstimateError,
    IncompatibleTemporalSupportError,
    UnverifiedUnitContractError,
    AssetUnitContract,
    assert_annualizable,
    assert_is_stock_metric,
    assert_within_envelope,
    observation_quality_flags,
)
from app.services.geospatial.biomass.stocking_capacity import (
    annual_demand_t_dm_per_ua,
    estimate_annual_potential_capacity,
    estimate_period_capacity,
)


def _monthly(value_per_ha: float = 1.42, **overrides) -> BiomassEstimate:
    kwargs = dict(
        metric_type="monthly_dry_matter_productivity",
        source="Time2Graze uGPP",
        source_version="v1",
        period_start=datetime.date(2026, 8, 1),
        period_end=datetime.date(2026, 9, 1),
        temporal_support="monthly",
        value_per_ha=value_per_ha,
        total_value=None if value_per_ha is None else value_per_ha * 23.6,
        unit_per_ha="t_DM_ha_month",
        total_unit="t_DM_month",
        raster_resolution_m=10.0,
        effective_mask_resolution_m=30.0,
        pasture_mask_source="Global Pasture Watch",
        pasture_mask_reference_year=2024,
        valid_area_ha=23.6,
        valid_observation_fraction=0.91,
        conversion_factors={"asset_scale": 0.01},
        model_version="monthly-productivity-v1",
    )
    kwargs.update(overrides)
    return BiomassEstimate(**kwargs)


def _annual(value_per_ha: float = 21.08, **overrides) -> BiomassEstimate:
    kwargs = dict(
        metric_type="annual_dry_matter_productivity",
        source="MapBiomas Brasil",
        source_version="Coleção 10",
        period_start=datetime.date(2024, 1, 1),
        period_end=datetime.date(2025, 1, 1),
        temporal_support="annual",
        value_per_ha=value_per_ha,
        total_value=value_per_ha * 23.6,
        unit_per_ha="t_DM_ha_year",
        total_unit="t_DM_year",
        raster_resolution_m=30.0,
        pasture_mask_source="MapBiomas",
        pasture_mask_reference_year=2024,
        valid_area_ha=23.6,
        conversion_factors={},
        model_version="annual-productivity-v1",
    )
    kwargs.update(overrides)
    return BiomassEstimate(**kwargs)


def _standing(value_per_ha: float = 2.8, **overrides) -> BiomassEstimate:
    kwargs = dict(
        metric_type="standing_dry_matter_biomass",
        source="Modelo supervisionado calibrado em campo",
        source_version="lightgbm",
        period_start=datetime.date(2026, 8, 22),
        period_end=datetime.date(2026, 9, 21),
        temporal_support="instantaneous",
        value_per_ha=value_per_ha,
        total_value=value_per_ha * 21.0,
        unit_per_ha="t_DM_ha",
        total_unit="t_DM",
        raster_resolution_m=10.0,
        effective_mask_resolution_m=30.0,
        pasture_mask_source="Global Pasture Watch + on-the-fly",
        pasture_mask_reference_year=2024,
        valid_area_ha=21.0,
        valid_observation_fraction=0.87,
        lower_bound_per_ha=2.1,
        upper_bound_per_ha=3.6,
        uncertainty_method="quantis P10/P90",
        conversion_factors={},
        model_version="standing-biomass-v1",
        quality_flags=["cloud_coverage_moderate", "pasture_mask_disagreement_low"],
    )
    kwargs.update(overrides)
    return BiomassEstimate(**kwargs)


# -----------------------------------------------------------------------------
# Requisito 5: proibição de calcular UA com métrica mensal
# -----------------------------------------------------------------------------

def test_monthly_productivity_cannot_produce_annual_stocking_capacity():
    """
    A guarda central da arquitetura.

    biomassa_mensal / 8,2 t MS/UA/ano subestima a capacidade em ~12x.
    """
    with pytest.raises(IncompatibleTemporalSupportError, match="suporte temporal anual"):
        estimate_annual_potential_capacity(_monthly(), pasture_area_ha=23.6)


def test_standing_biomass_cannot_produce_annual_stocking_capacity():
    with pytest.raises(IncompatibleTemporalSupportError):
        estimate_annual_potential_capacity(_standing(), pasture_area_ha=21.0)


def test_available_forage_cannot_produce_annual_stocking_capacity():
    forage = estimate_available_forage(_standing())

    with pytest.raises(IncompatibleTemporalSupportError):
        estimate_annual_potential_capacity(forage, pasture_area_ha=21.0)


def test_annual_metric_covering_only_part_of_the_year_is_rejected():
    short = _annual(period_end=datetime.date(2024, 7, 1))

    with pytest.raises(IncompatibleTemporalSupportError, match="182 dias"):
        estimate_annual_potential_capacity(short, pasture_area_ha=23.6)


def test_assert_annualizable_accepts_a_full_year():
    assert_annualizable(
        metric_type="annual_dry_matter_productivity",
        temporal_support="annual",
        period_days=366,
    )


def test_annual_demand_reproduces_the_lapig_divisor():
    """8,2 t MS/UA/ano derivado dos componentes, não escrito como constante mágica."""
    assert annual_demand_t_dm_per_ua() == pytest.approx(8.2125, abs=1e-4)


def test_annual_capacity_matches_the_manual_calculation():
    capacity = estimate_annual_potential_capacity(
        _annual(value_per_ha=21.08), pasture_area_ha=23.6, reported_stocking_ua=50.0,
    )

    expected_total_dm = 21.08 * 23.6
    expected_ua = expected_total_dm / annual_demand_t_dm_per_ua()

    assert capacity.annual_potential_capacity_ua == pytest.approx(expected_ua)
    assert capacity.annual_potential_capacity_ua_ha == pytest.approx(expected_ua / 23.6)
    assert capacity.reported_stocking_ua == 50.0
    assert capacity.reported_stocking_ua_ha == pytest.approx(50.0 / 23.6)
    # 50 UA declaradas contra ~60,6 UA de capacidade: sobra de forragem.
    assert capacity.annual_potential_capacity_ua == pytest.approx(60.6, abs=0.1)
    assert capacity.forage_balance_t_dm == pytest.approx(
        expected_total_dm - 50.0 * annual_demand_t_dm_per_ua()
    )
    assert capacity.forage_balance_t_dm > 0
    assert capacity.period_capacity_ua is None


def test_overstocking_shows_a_negative_forage_balance():
    capacity = estimate_annual_potential_capacity(
        _annual(value_per_ha=21.08), pasture_area_ha=23.6, reported_stocking_ua=90.0,
    )

    assert capacity.reported_stocking_ua > capacity.annual_potential_capacity_ua
    assert capacity.forage_balance_t_dm < 0


def test_annual_capacity_keeps_the_four_quantities_separate():
    capacity = estimate_annual_potential_capacity(_annual(), pasture_area_ha=23.6)

    text = str(capacity)
    assert "Capacidade anual potencial" in text
    assert "Capacidade no período" not in text
    assert "POTENCIAL" in " ".join(capacity.limitations)


# -----------------------------------------------------------------------------
# Capacidade no período (a via legítima sem base anual)
# -----------------------------------------------------------------------------

def test_period_capacity_requires_available_forage():
    with pytest.raises(ValueError, match="available_forage"):
        estimate_period_capacity(_monthly(), grazing_days=30, pasture_area_ha=23.6)


def test_period_capacity_matches_the_manual_calculation():
    forage = estimate_available_forage(
        _standing(value_per_ha=2.8),
        parameters=default_parameters("rotacionado"),
    )

    capacity = estimate_period_capacity(forage, grazing_days=30, pasture_area_ha=21.0)

    expected_forage_t_ha = (2.8 - 1.5) * 0.55
    daily_demand = 450.0 * 0.025 * 2.0 / 1000.0
    expected_ua = expected_forage_t_ha * 21.0 / (daily_demand * 30)

    assert capacity.period_capacity_ua == pytest.approx(expected_ua)
    assert capacity.period_days == 30
    assert capacity.annual_potential_capacity_ua is None
    assert "period_capacity_not_annual" in capacity.quality_flags


def test_period_capacity_rejects_a_non_positive_horizon():
    forage = estimate_available_forage(_standing())

    with pytest.raises(ValueError, match="pelo menos 1 dia"):
        estimate_period_capacity(forage, grazing_days=0, pasture_area_ha=21.0)


def test_capacity_without_pasture_area_is_refused():
    with pytest.raises(ValueError, match="Área de pastagem"):
        estimate_annual_potential_capacity(_annual(valid_area_ha=None), pasture_area_ha=None)


# -----------------------------------------------------------------------------
# Forragem disponível: só sobre estoque
# -----------------------------------------------------------------------------

def test_available_forage_cannot_be_derived_from_productivity():
    """Descontar resíduo de uma produtividade mistura fluxo com estoque."""
    for estimate in (_monthly(), _annual()):
        with pytest.raises(IncompatibleTemporalSupportError, match="produtividade"):
            estimate_available_forage(estimate)


def test_assert_is_stock_metric_accepts_standing_and_forage():
    assert_is_stock_metric("standing_dry_matter_biomass")
    assert_is_stock_metric("available_forage")


def test_available_forage_formula():
    assert compute_available_forage_t_ha(2.8, 1.5, 0.55) == pytest.approx(0.715)


def test_available_forage_never_goes_negative():
    """Biomassa em pé abaixo do resíduo mínimo significa zero forragem, não dívida."""
    assert compute_available_forage_t_ha(1.0, 1.5, 0.55) == 0.0

    forage = estimate_available_forage(
        _standing(value_per_ha=1.0, lower_bound_per_ha=0.8, upper_bound_per_ha=1.2),
        parameters=default_parameters("rotacionado"),
    )

    assert forage.value_per_ha == 0.0
    assert "below_residual_threshold" in forage.quality_flags


def test_available_forage_reports_the_parameters_it_used():
    forage = estimate_available_forage(
        _standing(), parameters=default_parameters("rotacionado", season="seca"),
    )

    assert forage.conversion_factors["residual_dm_t_ha"] == 1.5
    assert forage.conversion_factors["utilization_rate"] == pytest.approx(0.55 * 0.70)
    assert any("Resíduo mínimo" in item for item in forage.limitations)
    assert any("Fonte:" in item for item in forage.limitations)


def test_available_forage_propagates_uncertainty_and_flags():
    forage = estimate_available_forage(_standing())

    assert forage.lower_bound_per_ha is not None
    assert forage.upper_bound_per_ha is not None
    assert forage.lower_bound_per_ha < forage.value_per_ha < forage.upper_bound_per_ha
    assert "cloud_coverage_moderate" in forage.quality_flags
    assert "propagado de" in forage.uncertainty_method


def test_available_forage_subtracts_excluded_area_from_the_total():
    forage = estimate_available_forage(
        _standing(), parameters=default_parameters("continuo", excluded_area_ha=6.0),
    )

    assert forage.valid_area_ha == pytest.approx(15.0)
    assert forage.total_value == pytest.approx(forage.value_per_ha * 15.0)


def test_seasonal_adjustment_lowers_utilization_in_the_dry_season():
    wet = default_parameters("rotacionado", season="aguas")
    dry = default_parameters("rotacionado", season="seca")

    assert dry.utilization_rate < wet.utilization_rate


def test_unknown_management_system_is_refused():
    with pytest.raises(ValueError, match="desconhecido"):
        default_parameters("extensivo_tradicional")


# -----------------------------------------------------------------------------
# Requisito 4: dados faltantes e fallback explícito
# -----------------------------------------------------------------------------

def test_annualization_refuses_an_incomplete_series():
    """Sem 12 meses não há produtividade anual — e portanto não há UA/ano."""
    with pytest.raises(ValueError, match="12 meses"):
        annualize_monthly_series([_monthly()] * 11)


def test_annualization_refuses_a_series_with_a_gap():
    months = []
    for index in range(12):
        # Pula fevereiro: a série fica com 12 itens mas com buraco.
        month = index + 1 if index < 1 else index + 2
        year = 2025 + (month - 1) // 12
        month = (month - 1) % 12 + 1
        start = datetime.date(year, month, 1)
        end = datetime.date(year + (month == 12), month % 12 + 1, 1)
        months.append(_monthly(period_start=start, period_end=end))

    with pytest.raises(ValueError, match="Buraco na série"):
        annualize_monthly_series(months)


def test_annualization_refuses_a_series_with_a_missing_value():
    months = []
    for month in range(1, 13):
        start = datetime.date(2025, month, 1)
        end = datetime.date(2025 + (month == 12), month % 12 + 1, 1)
        value = None if month == 7 else 1.2
        months.append(_monthly(
            value_per_ha=value, total_value=None, period_start=start, period_end=end
        ))

    with pytest.raises(ValueError, match="sem valor estimado"):
        annualize_monthly_series(months)


def test_annualization_refuses_mixed_metric_types():
    months = [_monthly()] * 11 + [_annual()]

    with pytest.raises(ValueError, match="monthly_dry_matter_productivity"):
        annualize_monthly_series(months)


def test_a_complete_series_annualizes_and_unlocks_capacity():
    months = []
    for month in range(1, 13):
        start = datetime.date(2025, month, 1)
        end = datetime.date(2025 + (month == 12), month % 12 + 1, 1)
        months.append(_monthly(value_per_ha=1.2, period_start=start, period_end=end))

    annual = annualize_monthly_series(months)

    assert annual.metric_type == "annual_dry_matter_productivity"
    assert annual.temporal_support == "annual"
    assert annual.unit_per_ha == "t_DM_ha_year"
    assert annual.value_per_ha == pytest.approx(14.4)
    assert "annualized_from_monthly_series" in annual.quality_flags

    capacity = estimate_annual_potential_capacity(annual, pasture_area_ha=23.6)
    assert capacity.annual_potential_capacity_ua > 0
    assert any("anualizada" in item for item in capacity.limitations)


def test_observation_flags_escalate_with_cloud_cover():
    assert observation_quality_flags(0.95) == []
    assert "cloud_coverage_moderate" in observation_quality_flags(0.45)
    assert "cloud_coverage_high" in observation_quality_flags(0.10)
    assert "valid_observation_fraction_unknown" in observation_quality_flags(None)


# -----------------------------------------------------------------------------
# Envelope agronômico e contratos
# -----------------------------------------------------------------------------

def test_the_old_ten_fold_scale_error_is_caught_by_the_envelope():
    """Uma produtividade mensal de 14,2 t MS/ha é 10x o plausível."""
    with pytest.raises(ImplausibleEstimateError, match="fora do envelope"):
        assert_within_envelope("monthly_dry_matter_productivity", 14.2)


def test_plausible_values_pass_the_envelope():
    assert assert_within_envelope("monthly_dry_matter_productivity", 1.42) == []
    assert assert_within_envelope("annual_dry_matter_productivity", 21.08) == []
    assert assert_within_envelope("standing_dry_matter_biomass", 2.8) == []


def test_values_near_the_ceiling_are_flagged_but_allowed():
    ceiling = AGRONOMIC_ENVELOPES["monthly_dry_matter_productivity"][1]

    assert "value_near_upper_envelope" in assert_within_envelope(
        "monthly_dry_matter_productivity", ceiling * 0.9
    )


def test_missing_value_passes_the_envelope_without_flags():
    assert assert_within_envelope("standing_dry_matter_biomass", None) == []


def test_negative_values_are_refused():
    with pytest.raises(ImplausibleEstimateError):
        assert_within_envelope("standing_dry_matter_biomass", -0.5)


def test_unverified_contract_cannot_emit_an_estimate():
    contract = AssetUnitContract(
        asset_id="projects/teste/asset",
        band="x", dtype="uint16", stored_scale=1.0, native_unit="?",
        temporal_support="instantaneous", nominal_resolution_m=10.0,
        observation_cadence_days=None, missing_data_policy="?",
        producer="?", producer_version=None, documentation_url=None,
        verification_status="unverified",
    )

    with pytest.raises(UnverifiedUnitContractError, match="unverified"):
        contract.require(minimum_status="inferred")
