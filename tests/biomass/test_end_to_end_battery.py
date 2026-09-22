"""
Bateria de validação de ponta a ponta da arquitetura de biomassa.

Diferente dos outros arquivos, que testam cada módulo isoladamente, esta bateria
percorre o sistema de cima a baixo e cobre as combinações que a operação real
produz: todas as métricas, todos os caminhos de recusa, todas as bordas de data,
a coerência de unidades ao longo da cadeia e a exposição das travas no nível das
ferramentas do agente.

Está organizada em blocos:

    A. Invariantes de unidade e conceito  - o que nunca pode ser trocado
    B. Bordas de calendário               - toda combinação de data
    C. Matriz de recusas                  - toda métrica x toda base incompatível
    D. Cadeia numérica                    - a conta fecha de ponta a ponta
    E. Superfície do agente               - as travas estão expostas como tools
    F. Robustez                           - valores extremos e degenerados

    PYTHONPATH=. .venv/bin/python -m pytest tests/biomass/test_end_to_end_battery.py -v
"""
import calendar
import datetime
import inspect
import itertools

import pytest

from app.schemas.biomass_schemas import (
    METRIC_LABELS,
    METRIC_TEMPORAL_SUPPORT,
    METRIC_UNITS,
    BiomassEstimate,
    ForageParameters,
)
from app.services.geospatial.biomass.available_forage import (
    MANAGEMENT_DEFAULTS,
    SEASONAL_UTILIZATION_ADJUSTMENT,
    compute_available_forage_t_ha,
    default_parameters,
    estimate_available_forage,
)
from app.services.geospatial.biomass.biomass_productivity import (
    MIN_OBSERVABLE_DAYS,
    annual_period,
    annualize_monthly_series,
    daily_rate_to_dry_matter_t_ha,
    dry_matter_conversion_factors,
    is_partial_month,
    monthly_period,
)
from app.services.geospatial.biomass.biomass_validation import (
    AGRONOMIC_ENVELOPES,
    ASSET_CONTRACTS,
    ImplausibleEstimateError,
    IncompatibleTemporalSupportError,
    assert_annualizable,
    assert_is_stock_metric,
    assert_within_envelope,
    build_cache_key,
)
from app.services.geospatial.biomass.historical_biomass import (
    gpp_to_dry_matter_t_ha,
    historical_conversion_factors,
    historical_uncertainty_bounds,
)
from app.services.geospatial.biomass.stocking_capacity import (
    annual_demand_t_dm_per_ua,
    daily_demand_t_dm_per_ua,
    estimate_annual_potential_capacity,
    estimate_period_capacity,
)


_SQUARE = [[[[-50.6, -16.3], [-50.6, -16.2], [-50.5, -16.2], [-50.5, -16.3], [-50.6, -16.3]]]]

_ALL_METRICS = tuple(METRIC_UNITS)
_PRODUCTIVITY = ("monthly_dry_matter_productivity", "annual_dry_matter_productivity")
_STOCK = ("standing_dry_matter_biomass", "available_forage")


def _estimate(metric_type: str, value: float = 1.0, **overrides) -> BiomassEstimate:
    """Estimativa mínima válida de qualquer métrica, para exercitar as travas."""
    per_ha, total = METRIC_UNITS[metric_type]
    support = METRIC_TEMPORAL_SUPPORT[metric_type]

    if support == "annual":
        start, end = datetime.date(2024, 1, 1), datetime.date(2025, 1, 1)
    elif support == "monthly":
        start, end = datetime.date(2026, 8, 1), datetime.date(2026, 9, 1)
    else:
        start, end = datetime.date(2026, 8, 22), datetime.date(2026, 9, 21)

    kwargs = dict(
        metric_type=metric_type,
        source="fonte de teste",
        period_start=start,
        period_end=end,
        temporal_support=support,
        value_per_ha=value,
        total_value=None if value is None else value * 20.0,
        unit_per_ha=per_ha,
        total_unit=total,
        raster_resolution_m=30.0,
        effective_mask_resolution_m=30.0,
        pasture_mask_source="Global Pasture Watch",
        pasture_mask_reference_year=2024,
        valid_area_ha=20.0,
        conversion_factors={},
        model_version="battery",
    )
    kwargs.update(overrides)
    return BiomassEstimate(**kwargs)


# =============================================================================
# A. Invariantes de unidade e conceito
# =============================================================================

@pytest.mark.parametrize("metric_type", _ALL_METRICS)
def test_every_metric_has_one_canonical_unit_pair(metric_type):
    """Cada métrica tem exatamente um par de unidades, e o schema exige esse par."""
    per_ha, total = METRIC_UNITS[metric_type]

    assert _estimate(metric_type).unit_per_ha == per_ha
    assert _estimate(metric_type).total_unit == total


@pytest.mark.parametrize("metric_type,wrong_unit", [
    (metric, unit)
    for metric in _ALL_METRICS
    for unit in {pair[0] for pair in METRIC_UNITS.values()}
    if unit != METRIC_UNITS[metric][0]
])
def test_no_metric_accepts_another_metrics_unit(metric_type, wrong_unit):
    """Nenhuma métrica aceita a unidade de outra — a troca é barrada na validação."""
    with pytest.raises(Exception, match="unit_per_ha"):
        _estimate(metric_type, unit_per_ha=wrong_unit)


@pytest.mark.parametrize("metric_type,wrong_support", [
    (metric, support)
    for metric in _ALL_METRICS
    for support in ("monthly", "annual", "instantaneous")
    if support != METRIC_TEMPORAL_SUPPORT[metric]
])
def test_no_metric_accepts_another_temporal_support(metric_type, wrong_support):
    with pytest.raises(Exception, match="temporal_support"):
        _estimate(metric_type, temporal_support=wrong_support)


@pytest.mark.parametrize("metric_type", _ALL_METRICS)
def test_every_metric_has_a_portuguese_label_and_envelope(metric_type):
    """Toda métrica é exibível e tem faixa agronômica — nenhuma fica sem contexto."""
    assert metric_type in METRIC_LABELS and METRIC_LABELS[metric_type]
    assert metric_type in AGRONOMIC_ENVELOPES

    low, high = AGRONOMIC_ENVELOPES[metric_type]
    assert 0 <= low < high


@pytest.mark.parametrize("metric_type", _ALL_METRICS)
def test_report_block_always_carries_the_mandatory_fields(metric_type):
    """Nenhum número circula sem métrica, fonte, período, unidade e resoluções."""
    block = _estimate(metric_type).to_report_block()

    for label in ("Métrica:", "Fonte:", "Período:", "Unidade:",
                  "Resolução do raster:", "Resolução efetiva da máscara:",
                  "Cobertura válida:", "Incerteza:", "Versão:"):
        assert label in block, f"{metric_type} sem '{label}'"


@pytest.mark.parametrize("metric_type", _PRODUCTIVITY)
def test_productivity_is_flagged_as_flow(metric_type):
    assert _estimate(metric_type).is_productivity is True


@pytest.mark.parametrize("metric_type", _STOCK)
def test_stock_is_not_flagged_as_flow(metric_type):
    assert _estimate(metric_type).is_productivity is False


def test_every_registered_asset_has_a_documented_scale_and_evidence():
    """Nenhum asset entra no sistema sem contrato de unidade e evidência."""
    assert ASSET_CONTRACTS, "nenhum contrato registrado"

    for asset_id, contract in ASSET_CONTRACTS.items():
        assert contract.stored_scale > 0, asset_id
        assert contract.nominal_resolution_m > 0, asset_id
        assert contract.native_unit, asset_id
        assert contract.verification_status in ("documented", "inferred", "unverified"), asset_id
        if contract.verification_status == "inferred":
            assert contract.evidence, f"{asset_id} inferido sem evidência registrada"


# =============================================================================
# B. Bordas de calendário
# =============================================================================

@pytest.mark.parametrize("month", range(1, 13))
def test_every_month_of_a_past_year_spans_its_real_length(month):
    """Os 12 meses, com o número de dias correto, sem mês parcial."""
    start, end = monthly_period(2025, month, today=datetime.date(2026, 9, 21))

    assert start == datetime.date(2025, month, 1)
    assert (end - start).days == calendar.monthrange(2025, month)[1]
    assert is_partial_month(start, end) is False


@pytest.mark.parametrize("year,expected", [(2024, 29), (2025, 28), (2026, 28), (2028, 29)])
def test_february_length_follows_the_leap_rule(year, expected):
    start, end = monthly_period(year, 2, today=datetime.date(2029, 1, 1))

    assert (end - start).days == expected


@pytest.mark.parametrize("month", range(1, 13))
def test_december_to_january_transition_never_loses_a_day(month):
    """A soma dos 12 meses de um ano fecha exatamente com o período anual."""
    total = sum(
        (monthly_period(2025, m, today=datetime.date(2026, 9, 21))[1]
         - monthly_period(2025, m, today=datetime.date(2026, 9, 21))[0]).days
        for m in range(1, 13)
    )
    annual_start, annual_end = annual_period(2025)

    assert total == (annual_end - annual_start).days == 365


def test_the_first_day_of_a_month_has_no_observable_period():
    """
    No dia 1º o intervalo seria vazio.

    Sem esta guarda o Earth Engine levanta "Empty date ranges not supported" e,
    se passasse, zero dia de acumulação viraria 0,00 t MS/ha — que o produtor
    leria como pasto sem produção.
    """
    with pytest.raises(ValueError, match="começou hoje"):
        monthly_period(2026, 9, today=datetime.date(2026, 9, 1))


@pytest.mark.parametrize("day", range(2, 12))
def test_early_month_is_truncated_and_flagged_as_partial(day):
    start, end = monthly_period(2026, 9, today=datetime.date(2026, 9, day))

    assert (end - start).days == day - 1
    assert is_partial_month(start, end) is True


def test_a_future_month_is_refused():
    with pytest.raises(ValueError, match="ainda não começou"):
        monthly_period(2027, 1, today=datetime.date(2026, 9, 21))


@pytest.mark.parametrize("month", [-1, 0, 13, 99])
def test_month_outside_the_calendar_is_refused(month):
    with pytest.raises(ValueError, match="entre 1"):
        monthly_period(2026, month, today=datetime.date(2026, 9, 21))


@pytest.mark.parametrize("year", [2000, 2015, 2024, 2025])
def test_annual_period_is_always_a_whole_year(year):
    start, end = annual_period(year)

    assert start.month == start.day == 1
    assert end.year == year + 1
    assert (end - start).days in (365, 366)


def test_minimum_observable_days_is_a_sane_threshold():
    assert 1 < MIN_OBSERVABLE_DAYS < 28


# =============================================================================
# C. Matriz de recusas
# =============================================================================

@pytest.mark.parametrize("metric_type", [m for m in _ALL_METRICS if m != "annual_dry_matter_productivity"])
def test_no_non_annual_metric_produces_annual_capacity(metric_type):
    """A trava central: só base anual vira UA/ano. Testada para TODA outra métrica."""
    with pytest.raises(IncompatibleTemporalSupportError):
        estimate_annual_potential_capacity(_estimate(metric_type), pasture_area_ha=20.0)


@pytest.mark.parametrize("days", [1, 30, 90, 180, 349])
def test_an_annual_metric_covering_less_than_a_year_is_refused(days):
    short = _estimate(
        "annual_dry_matter_productivity",
        period_start=datetime.date(2024, 1, 1),
        period_end=datetime.date(2024, 1, 1) + datetime.timedelta(days=days),
    )

    with pytest.raises(IncompatibleTemporalSupportError, match=str(days)):
        estimate_annual_potential_capacity(short, pasture_area_ha=20.0)


@pytest.mark.parametrize("metric_type", _PRODUCTIVITY)
def test_no_productivity_metric_becomes_available_forage(metric_type):
    """Forragem é estoque menos resíduo; derivá-la de fluxo mistura conceitos."""
    with pytest.raises(IncompatibleTemporalSupportError, match="produtividade"):
        estimate_available_forage(_estimate(metric_type))


@pytest.mark.parametrize("metric_type", _STOCK)
def test_stock_metrics_pass_the_stock_guard(metric_type):
    assert_is_stock_metric(metric_type)


@pytest.mark.parametrize("metric_type", [m for m in _ALL_METRICS if m != "available_forage"])
def test_period_capacity_requires_available_forage(metric_type):
    with pytest.raises(ValueError, match="available_forage"):
        estimate_period_capacity(_estimate(metric_type), grazing_days=30, pasture_area_ha=20.0)


@pytest.mark.parametrize("grazing_days", [0, -1, -30])
def test_period_capacity_refuses_a_non_positive_horizon(grazing_days):
    forage = estimate_available_forage(_estimate("standing_dry_matter_biomass", value=3.0))

    with pytest.raises(ValueError, match="pelo menos 1 dia"):
        estimate_period_capacity(forage, grazing_days=grazing_days, pasture_area_ha=20.0)


@pytest.mark.parametrize("area", [None, 0.0, -5.0])
def test_capacity_refuses_a_missing_or_impossible_area(area):
    annual = _estimate("annual_dry_matter_productivity", value=21.0, valid_area_ha=None)

    with pytest.raises(ValueError, match="Área de pastagem"):
        estimate_annual_potential_capacity(annual, pasture_area_ha=area)


@pytest.mark.parametrize("n_months", [0, 1, 6, 11, 13, 24])
def test_annualization_requires_exactly_twelve_months(n_months):
    months = [_estimate("monthly_dry_matter_productivity", value=1.2)] * n_months

    with pytest.raises(ValueError, match="12 meses"):
        annualize_monthly_series(months)


def test_annualization_refuses_a_gap_in_the_series():
    months = []
    for index, month in enumerate([1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 12]):
        year = 2025 if index < 11 else 2026
        months.append(_estimate(
            "monthly_dry_matter_productivity", value=1.2,
            period_start=datetime.date(year, month, 1),
            period_end=(datetime.date(year + (month == 12), month % 12 + 1, 1)),
        ))

    with pytest.raises(ValueError, match="Buraco na série"):
        annualize_monthly_series(months)


def test_a_complete_series_annualizes_and_only_then_unlocks_capacity():
    """O único caminho legítimo do mensal até UA/ano."""
    months = [
        _estimate(
            "monthly_dry_matter_productivity", value=1.5,
            period_start=datetime.date(2025, m, 1),
            period_end=datetime.date(2025 + (m == 12), m % 12 + 1, 1),
        )
        for m in range(1, 13)
    ]

    annual = annualize_monthly_series(months)
    assert annual.temporal_support == "annual"
    assert annual.value_per_ha == pytest.approx(18.0)

    capacity = estimate_annual_potential_capacity(annual, pasture_area_ha=20.0)
    assert capacity.annual_potential_capacity_ua > 0


# =============================================================================
# D. Cadeia numérica
# =============================================================================

@pytest.mark.parametrize("dn,days", list(itertools.product([0, 100, 500, 1000, 2000], [1, 15, 28, 30, 31])))
def test_monthly_conversion_is_linear_and_exact(dn, days):
    """A conta mensal é determinística e linear nos dois eixos."""
    factors = dry_matter_conversion_factors()
    esperado = (
        dn * factors["asset_scale"] * factors["grass_fraction_or_lue"]
        * factors["carbon_to_dry_matter"] * days * factors["unit_conversion"]
    )

    assert daily_rate_to_dry_matter_t_ha(dn, days) == pytest.approx(esperado)


@pytest.mark.parametrize("ugpp", [0, 500, 1000, 1886, 2500])
def test_historical_conversion_reproduces_the_official_factor(ugpp):
    """Idêntico ao DRY_BIOMASS_FACTOR do script GPW/LAPIG."""
    assert gpp_to_dry_matter_t_ha(ugpp) == pytest.approx(ugpp * 0.50 * 2.3 * 0.01)


def test_monthly_and_historical_share_the_same_lue():
    """As duas fontes uGPP usam o mesmo LUEmax — não há cadeia paralela."""
    assert (
        dry_matter_conversion_factors()["grass_fraction_or_lue"]
        == historical_conversion_factors()["grass_fraction_or_lue"]
    )


def test_the_lapig_divisor_is_derived_not_hardcoded():
    assert annual_demand_t_dm_per_ua() == pytest.approx(8.2125, abs=1e-4)
    assert daily_demand_t_dm_per_ua() * 365 == pytest.approx(annual_demand_t_dm_per_ua())


@pytest.mark.parametrize("value,area", list(itertools.product([5.0, 15.0, 21.08, 40.0], [1.0, 20.0, 500.0])))
def test_annual_capacity_matches_the_closed_form(value, area):
    annual = _estimate("annual_dry_matter_productivity", value=value)
    capacity = estimate_annual_potential_capacity(annual, pasture_area_ha=area)

    assert capacity.annual_potential_capacity_ua == pytest.approx(
        value * area / annual_demand_t_dm_per_ua()
    )
    assert capacity.annual_potential_capacity_ua_ha == pytest.approx(
        capacity.annual_potential_capacity_ua / area
    )


@pytest.mark.parametrize("standing,residual,rate", list(itertools.product(
    [0.0, 1.0, 2.8, 6.0], [0.0, 1.5, 2.0], [0.4, 0.55, 0.65])))
def test_available_forage_never_goes_negative_and_matches_the_formula(standing, residual, rate):
    resultado = compute_available_forage_t_ha(standing, residual, rate)

    assert resultado >= 0.0
    assert resultado == pytest.approx(max(standing - residual, 0.0) * rate)


@pytest.mark.parametrize("system", list(MANAGEMENT_DEFAULTS))
@pytest.mark.parametrize("season", [None, *SEASONAL_UTILIZATION_ADJUSTMENT])
def test_every_management_and_season_combination_is_coherent(system, season):
    params = default_parameters(system, season=season)

    assert 0 < params.utilization_rate <= 1.0
    assert params.residual_dm_t_ha >= 0
    assert params.source
    if season == "seca":
        assert params.utilization_rate < MANAGEMENT_DEFAULTS[system]["utilization_rate"]


def test_dry_season_is_never_more_permissive_than_the_wet_season():
    for system in MANAGEMENT_DEFAULTS:
        seca = default_parameters(system, season="seca").utilization_rate
        aguas = default_parameters(system, season="aguas").utilization_rate
        assert seca <= aguas, system


@pytest.mark.parametrize("value", [1.0, 10.0, 21.69, 30.0])
def test_historical_uncertainty_always_brackets_the_central_value(value):
    lower, upper = historical_uncertainty_bounds(value)

    assert lower <= value <= upper
    assert upper / lower == pytest.approx(2.7 / 2.3)


def test_forage_uncertainty_is_propagated_from_standing_biomass():
    standing = _estimate(
        "standing_dry_matter_biomass", value=2.8,
        lower_bound_per_ha=2.1, upper_bound_per_ha=3.6,
        uncertainty_method="quantis P10/P90",
    )
    forage = estimate_available_forage(standing, parameters=default_parameters("rotacionado"))

    assert forage.lower_bound_per_ha == pytest.approx(compute_available_forage_t_ha(2.1, 1.5, 0.55))
    assert forage.upper_bound_per_ha == pytest.approx(compute_available_forage_t_ha(3.6, 1.5, 0.55))
    assert forage.lower_bound_per_ha <= forage.value_per_ha <= forage.upper_bound_per_ha


@pytest.mark.parametrize("metric_type", _ALL_METRICS)
def test_the_envelope_rejects_a_ten_fold_scale_error(metric_type):
    """Um erro de escala de 10x sai do envelope em qualquer métrica."""
    _, high = AGRONOMIC_ENVELOPES[metric_type]

    with pytest.raises(ImplausibleEstimateError):
        assert_within_envelope(metric_type, high * 10)


@pytest.mark.parametrize("metric_type", _ALL_METRICS)
def test_the_envelope_rejects_negative_values(metric_type):
    with pytest.raises(ImplausibleEstimateError):
        assert_within_envelope(metric_type, -1.0)


def test_cache_key_changes_with_every_semantic_input():
    """Qualquer coisa que mude o número tem que mudar a chave."""
    base = dict(
        metric_type="monthly_dry_matter_productivity", coords=_SQUARE,
        period_start=datetime.date(2026, 8, 1), period_end=datetime.date(2026, 9, 1),
        model_version="v1", conversion_factors=dry_matter_conversion_factors(),
        mask_signature="GPW|v1-1|2024|30|official",
    )
    referencia = build_cache_key(**base)

    variacoes = [
        {"metric_type": "annual_dry_matter_productivity"},
        {"coords": [[[[-51.0, -16.3], [-51.0, -16.2], [-50.9, -16.2], [-51.0, -16.3]]]]},
        {"period_start": datetime.date(2026, 7, 1)},
        {"period_end": datetime.date(2026, 10, 1)},
        {"model_version": "v2"},
        {"conversion_factors": {**dry_matter_conversion_factors(), "asset_scale": 0.1}},
        {"mask_signature": "GPW|v1-1|2023|30|official"},
    ]
    for variacao in variacoes:
        assert build_cache_key(**{**base, **variacao}) != referencia, variacao


# =============================================================================
# E. Superfície do agente
# =============================================================================

def test_stocking_capacity_is_exposed_as_a_tool():
    """
    A trava só vale se o agente for obrigado a passar por ela.

    Sem esta ferramenta o modelo calcula UA sozinho com a calculadora genérica —
    exatamente o cálculo inseguro que a arquitetura existe para impedir.
    """
    from app.tools import analysis_tools

    assert hasattr(analysis_tools, "get_stocking_capacity")


def test_the_capacity_tool_is_registered_with_the_agent():
    from app.agents.single_agent import _ANALYST_TOOLS

    nomes = {getattr(t, "name", getattr(t, "__name__", "")) for t in _ANALYST_TOOLS}
    assert "get_stocking_capacity" in nomes


def test_the_agent_is_told_never_to_compute_animal_units_itself():
    from app.configs.prompts import get_agent_field

    instrucoes = get_agent_field("single_agent", "instructions_default")

    assert "get_stocking_capacity" in instrucoes
    assert any(t in instrucoes for t in ("NUNCA calcule capacidade", "NEVER compute stocking"))


@pytest.mark.parametrize("tool_name", [
    "generate_biomass_image",
    "generate_biomass_video",
    "generate_historical_biomass_series",
    "get_stocking_capacity",
    "get_pasture_stats",
])
def test_every_biomass_tool_has_description_and_result_texts(tool_name):
    """Nenhuma ferramenta chega ao agente sem descrição e sem textos de retorno."""
    from app.configs.prompts import get_tool_description, get_tool_result_text

    assert get_tool_description("analysis_tools", tool_name).strip()
    assert get_tool_result_text(
        "analysis_tools", tool_name, "feature_not_found", feature_id="X"
    ).strip()


@pytest.mark.parametrize("tool_name", [
    "get_stocking_capacity", "generate_historical_biomass_series", "generate_biomass_image",
])
def test_tool_descriptions_warn_against_metric_confusion(tool_name):
    from app.configs.prompts import get_tool_description

    texto = get_tool_description("analysis_tools", tool_name).lower()
    assert any(t in texto for t in ("nunca", "não é", "never", "not "))


def test_the_capacity_tool_accepts_the_management_parameters():
    from app.tools.analysis_tools import get_stocking_capacity

    fn = getattr(get_stocking_capacity, "entrypoint", get_stocking_capacity)
    params = inspect.signature(fn).parameters

    for nome in ("feature_id", "reported_stocking_ua", "grazing_days", "management_system"):
        assert nome in params, f"parâmetro ausente: {nome}"


# =============================================================================
# F. Robustez
# =============================================================================

@pytest.mark.parametrize("metric_type", _ALL_METRICS)
def test_a_metric_without_value_is_reported_as_unavailable(metric_type):
    estimate = _estimate(metric_type, value=None, total_value=None)
    bloco = estimate.to_report_block()

    assert "indisponível" in bloco
    assert assert_within_envelope(metric_type, None) == []


def test_zero_productivity_is_a_valid_value_not_an_error():
    """Pasto sem produção no período é resultado legítimo, não falha."""
    assert assert_within_envelope("monthly_dry_matter_productivity", 0.0) == []
    assert daily_rate_to_dry_matter_t_ha(0.0, 31) == 0.0


def test_forage_below_the_residual_is_zero_and_flagged():
    standing = _estimate("standing_dry_matter_biomass", value=1.0)
    forage = estimate_available_forage(standing, parameters=default_parameters("continuo"))

    assert forage.value_per_ha == 0.0
    assert "below_residual_threshold" in forage.quality_flags


def test_capacity_with_zero_forage_is_zero_not_a_crash():
    standing = _estimate("standing_dry_matter_biomass", value=0.5)
    forage = estimate_available_forage(standing, parameters=default_parameters("continuo"))
    capacity = estimate_period_capacity(forage, grazing_days=30, pasture_area_ha=20.0)

    assert capacity.period_capacity_ua == 0.0


@pytest.mark.parametrize("reported", [0.0, 1.0, 50.0, 1000.0])
def test_forage_balance_sign_follows_the_comparison(reported):
    annual = _estimate("annual_dry_matter_productivity", value=21.0)
    capacity = estimate_annual_potential_capacity(
        annual, pasture_area_ha=20.0, reported_stocking_ua=reported
    )

    if reported < capacity.annual_potential_capacity_ua:
        assert capacity.forage_balance_t_dm > 0
    elif reported > capacity.annual_potential_capacity_ua:
        assert capacity.forage_balance_t_dm < 0


def test_excluded_area_never_produces_a_negative_area():
    standing = _estimate("standing_dry_matter_biomass", value=3.0, valid_area_ha=10.0)
    forage = estimate_available_forage(
        standing, parameters=default_parameters("continuo", excluded_area_ha=999.0)
    )

    assert forage.valid_area_ha == 0.0
    assert forage.total_value == 0.0


@pytest.mark.parametrize("system", ["inexistente", "", "EXTENSIVO"])
def test_unknown_management_system_is_refused(system):
    with pytest.raises(ValueError, match="desconhecido"):
        default_parameters(system)


@pytest.mark.parametrize("season", ["verao", "inverno", ""])
def test_unknown_season_is_refused(season):
    with pytest.raises(ValueError, match="desconhecida"):
        default_parameters("continuo", season=season)


@pytest.mark.parametrize("rate", [0.0, -0.1, 1.01, 2.0])
def test_impossible_utilization_rate_is_refused(rate):
    with pytest.raises(Exception):
        ForageParameters(
            residual_dm_t_ha=1.5, utilization_rate=rate,
            management_system="continuo", source="teste",
        )


def test_capacity_string_never_mixes_annual_and_period_quantities():
    """As quatro grandezas ficam separadas na apresentação."""
    annual = estimate_annual_potential_capacity(
        _estimate("annual_dry_matter_productivity", value=21.0), pasture_area_ha=20.0
    )
    forage = estimate_available_forage(_estimate("standing_dry_matter_biomass", value=3.0))
    period = estimate_period_capacity(forage, grazing_days=30, pasture_area_ha=20.0)

    assert "Capacidade anual potencial" in str(annual)
    assert "Capacidade no período" not in str(annual)

    assert "Capacidade no período" in str(period)
    assert "Capacidade anual potencial" not in str(period)
    assert "period_capacity_not_annual" in period.quality_flags


def test_assert_annualizable_accepts_only_a_full_year():
    assert_annualizable("annual_dry_matter_productivity", "annual", 365)
    assert_annualizable("annual_dry_matter_productivity", "annual", 366)

    with pytest.raises(IncompatibleTemporalSupportError):
        assert_annualizable("annual_dry_matter_productivity", "annual", 349)
