"""
Testes herméticos do schema de biomassa (sem GEE, sem credenciais).

Cobre os requisitos 6 (separação entre fonte mensal e anual) e 8 (legendas com
unidade e valores corretos).

    PYTHONPATH=. .venv/bin/python -m pytest tests/biomass/test_biomass_schemas.py -v
"""
import datetime

import pytest
from pydantic import ValidationError

from app.schemas.biomass_schemas import BiomassEstimate, ForageParameters, PastureMaskMetadata


def _build_monthly(**overrides) -> BiomassEstimate:
    kwargs = dict(
        metric_type="monthly_dry_matter_productivity",
        source="WRI Land & Carbon Lab - Time2Graze uGPP",
        source_version="v1",
        period_start=datetime.date(2026, 8, 1),
        period_end=datetime.date(2026, 9, 1),
        temporal_support="monthly",
        value_per_ha=1.42,
        total_value=33.5,
        unit_per_ha="t_DM_ha_month",
        total_unit="t_DM_month",
        raster_resolution_m=10.0,
        effective_mask_resolution_m=30.0,
        pasture_mask_source="Global Pasture Watch",
        pasture_mask_reference_year=2024,
        valid_area_ha=23.6,
        valid_observation_fraction=0.91,
        lower_bound_per_ha=1.14,
        upper_bound_per_ha=1.85,
        uncertainty_method="faixa de LUEmax",
        conversion_factors={"asset_scale": 0.01},
        model_version="monthly-productivity-v1",
    )
    kwargs.update(overrides)
    return BiomassEstimate(**kwargs)


def test_monthly_estimate_round_trips():
    estimate = _build_monthly()

    rebuilt = BiomassEstimate.model_validate(estimate.model_dump())

    assert rebuilt == estimate
    assert rebuilt.is_productivity is True
    assert rebuilt.is_annual is False
    assert rebuilt.period_days == 31


def test_monthly_unit_cannot_be_labelled_as_stock():
    """t MS/ha é unidade de estoque; produtividade mensal não pode usá-la."""
    with pytest.raises(ValidationError, match="unit_per_ha"):
        _build_monthly(unit_per_ha="t_DM_ha")


def test_monthly_total_unit_must_match_metric():
    with pytest.raises(ValidationError, match="total_unit"):
        _build_monthly(total_unit="t_DM_year")


def test_monthly_metric_cannot_declare_annual_support():
    """A separação mensal/anual é estrutural, não convenção de nomes."""
    with pytest.raises(ValidationError, match="temporal_support"):
        _build_monthly(temporal_support="annual")


def test_annual_metric_requires_annual_units_and_support():
    annual = BiomassEstimate(
        metric_type="annual_dry_matter_productivity",
        source="MapBiomas Brasil",
        source_version="Coleção 10",
        period_start=datetime.date(2024, 1, 1),
        period_end=datetime.date(2025, 1, 1),
        temporal_support="annual",
        value_per_ha=21.08,
        total_value=497.0,
        unit_per_ha="t_DM_ha_year",
        total_unit="t_DM_year",
        raster_resolution_m=30.0,
        pasture_mask_source="MapBiomas",
        conversion_factors={},
        model_version="annual-productivity-v1",
    )

    assert annual.is_annual is True
    assert annual.unit_label == "t MS/ha/ano"

    with pytest.raises(ValidationError, match="temporal_support"):
        annual.model_copy(update={"temporal_support": "monthly"}).model_validate(
            annual.model_dump() | {"temporal_support": "monthly"}
        )


def test_inverted_period_is_rejected():
    with pytest.raises(ValidationError, match="period_end"):
        _build_monthly(
            period_start=datetime.date(2026, 9, 1),
            period_end=datetime.date(2026, 8, 1),
        )


def test_bounds_require_an_uncertainty_method():
    with pytest.raises(ValidationError, match="uncertainty_method"):
        _build_monthly(uncertainty_method=None)


def test_inverted_bounds_are_rejected():
    with pytest.raises(ValidationError, match="lower_bound_per_ha"):
        _build_monthly(lower_bound_per_ha=2.0, upper_bound_per_ha=1.0)


def test_valid_observation_fraction_is_bounded():
    with pytest.raises(ValidationError, match="valid_observation_fraction"):
        _build_monthly(valid_observation_fraction=1.4)


def test_report_block_carries_every_mandatory_field():
    """Requisito 8: nenhum número sai sem métrica, fonte, período e unidade."""
    block = _build_monthly(
        pasture_mask=PastureMaskMetadata(
            source="Global Pasture Watch",
            source_version="ggc-30m v1-1",
            reference_year=2024,
            resolution_m=30.0,
            pasture_area_ha=21.0,
            property_area_ha=23.6,
            pasture_fraction=0.89,
        ),
        limitations=["estimativa de produtividade; não é forragem disponível."],
    ).to_report_block()

    for label in (
        "Métrica:", "Fonte:", "Período:", "Unidade:", "Resolução do raster:",
        "Resolução efetiva da máscara:", "Cobertura válida:", "Incerteza:",
        "Versão:", "Limitações:",
    ):
        assert label in block, f"bloco de metadados sem '{label}'"

    assert "Produtividade mensal de matéria seca estimada" in block
    assert "t MS/ha/mês" in block
    assert "01/08/2026 a 31/08/2026" in block
    assert "10 m" in block
    assert "30 m" in block
    assert "91%" in block


def test_report_block_states_when_value_is_missing():
    block = _build_monthly(
        value_per_ha=None, total_value=None,
        lower_bound_per_ha=None, upper_bound_per_ha=None, uncertainty_method=None,
    ).to_report_block()

    assert "Valor: indisponível" in block
    assert "Incerteza: não quantificada" in block


def test_period_label_shows_inclusive_last_day():
    """O período é armazenado com fim exclusivo mas exibido com o último dia real."""
    label = _build_monthly(
        period_start=datetime.date(2026, 1, 1), period_end=datetime.date(2026, 2, 1)
    ).period_label()

    assert label == "01/01/2026 a 31/01/2026"


def test_forage_parameters_reject_impossible_utilization():
    with pytest.raises(ValidationError):
        ForageParameters(
            residual_dm_t_ha=1.5, utilization_rate=1.6,
            management_system="rotacionado", source="teste",
        )

    with pytest.raises(ValidationError):
        ForageParameters(
            residual_dm_t_ha=-1.0, utilization_rate=0.5,
            management_system="rotacionado", source="teste",
        )


def test_forage_parameters_str_exposes_every_parameter_used():
    """Requisito: nunca assumir taxa universal sem mostrar o parâmetro utilizado."""
    text = str(ForageParameters(
        residual_dm_t_ha=1.5, utilization_rate=0.55,
        management_system="rotacionado", forage_species="Urochloa brizantha cv. Marandu",
        season="aguas", rest_period_days=28, animal_category="recria",
        current_stocking_ua_ha=1.2, excluded_area_ha=3.0, source="Embrapa",
    ))

    assert "1.50 t MS/ha" in text
    assert "55%" in text
    assert "rotacionado" in text
    assert "Marandu" in text
    assert "28 dias" in text
    assert "1.20 UA/ha" in text
    assert "3.00 ha" in text
    assert "Embrapa" in text
