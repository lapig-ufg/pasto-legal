"""
Testes de integração real contra o Earth Engine.

Precisam de um `.env` válido na raiz (GEE_PROJECT, GEE_SERVICE_ACCOUNT,
GEE_KEY_FILE, APP_ENV) porque `app.services.geospatial.gee` inicializa o Earth
Engine na importação do módulo.

Cobre os requisitos 2 (total via pixelArea), 7 (banda anual selecionada pelo
nome), 9 (máscara com ano, fonte e resolução expostos) e 12 (regressão com
propriedades reais e valores esperados).

    PYTHONPATH=. .venv/bin/python -m pytest tests/biomass/test_biomass_integration_gee.py -v
"""
import datetime
import json

from pathlib import Path

import ee
import pytest

from app.services.geospatial.biomass.biomass_productivity import (
    annual_productivity_band,
    available_annual_years,
    estimate_annual_productivity,
    estimate_monthly_productivity,
    latest_monthly_productivity,
    monthly_productivity_image,
    monthly_period,
)
from app.services.geospatial.biomass.biomass_validation import (
    MAPBIOMAS_PASTURE_BIOMASS_CONTRACT,
    NoDataForPeriodError,
    T2G_UGPP_CF_CONTRACT,
    T2G_UGPP_CONTRACTS,
)
from app.services.geospatial.biomass.pasture_mask import build_pasture_mask


_ROOT = Path(__file__).resolve().parents[2]
_MOCK_PATH = _ROOT / "app/utils/mocks/new_property_mock.json"

# Imóvel com cobertura Time2Graze confirmada em 21/09/2026 (tile 23MLT).
_COVERED_CAR = "GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0"

# Imóvel FORA da cobertura Time2Graze: é o caso de fallback explícito.
_UNCOVERED_CAR = "GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9"

# Área oficial declarada no CAR do imóvel coberto, em hectares.
_COVERED_AREA_HA = 23.4674


def _roi(car_code: str) -> ee.Geometry:
    """Geometria do imóvel de teste, a partir do mock do projeto."""
    features = json.loads(_MOCK_PATH.read_text())["features"]
    feature = next(item for item in features if item["properties"]["codigo"] == car_code)
    geometry = feature["geometry"]
    coords = (
        geometry["coordinates"] if geometry["type"] == "MultiPolygon"
        else [geometry["coordinates"]]
    )
    return ee.Geometry.MultiPolygon(coords)


@pytest.fixture(scope="module")
def covered_roi() -> ee.Geometry:
    return _roi(_COVERED_CAR)


@pytest.fixture(scope="module")
def covered_mask(covered_roi):
    return build_pasture_mask(roi=covered_roi, strategy="official")


# -----------------------------------------------------------------------------
# Requisito 9: máscara com ano, fonte e resolução expostos
# -----------------------------------------------------------------------------

def test_pasture_mask_exposes_source_year_and_resolution(covered_mask):
    metadata = covered_mask.metadata

    assert metadata.source
    assert metadata.source_version
    assert metadata.reference_year is not None
    assert metadata.resolution_m == pytest.approx(30.0)
    assert metadata.strategy == "official"

    assert metadata.property_area_ha == pytest.approx(_COVERED_AREA_HA, rel=0.05)
    assert metadata.pasture_area_ha is not None
    assert 0.0 <= metadata.pasture_fraction <= 1.0


def test_pasture_mask_signature_feeds_the_cache_key(covered_mask):
    signature = covered_mask.signature()

    assert covered_mask.metadata.source in signature
    assert str(covered_mask.metadata.reference_year) in signature
    assert "30" in signature


@pytest.mark.slow
def test_hybrid_mask_reports_disagreement_instead_of_hiding_it(covered_roi):
    """Requisito: divergência entre classificadores é sinalizada, não escondida."""
    mask = build_pasture_mask(roi=covered_roi, strategy="hybrid")

    assert mask.metadata.strategy == "hybrid"
    assert mask.metadata.disagreement_fraction is not None
    assert 0.0 <= mask.metadata.disagreement_fraction <= 1.0
    assert mask.metadata.classifier_version
    # A resolução efetiva do par é a da máscara mais grossa, não os 10 m do embedding.
    assert mask.metadata.resolution_m == pytest.approx(30.0)


# -----------------------------------------------------------------------------
# Requisito 7: banda anual do MapBiomas selecionada pelo nome
# -----------------------------------------------------------------------------

def test_annual_years_are_read_from_the_band_names():
    years = available_annual_years()

    assert years == sorted(years)
    assert 2000 in years
    assert years[-1] >= 2024


def test_annual_band_is_selected_by_name_not_by_index():
    assert annual_productivity_band(2024) == "biomass_2024"
    assert annual_productivity_band(2000) == "biomass_2000"

    bands = ee.Image(MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.asset_id).bandNames().getInfo()
    assert annual_productivity_band(2024) in bands


def test_requesting_an_unavailable_year_is_refused(covered_roi):
    with pytest.raises(ValueError, match="não existe"):
        estimate_annual_productivity(roi=covered_roi, year=1990)


# -----------------------------------------------------------------------------
# Requisitos 2 e 12: pixelArea e regressão com valores esperados
# -----------------------------------------------------------------------------

def test_annual_estimate_matches_the_known_property_values(covered_roi):
    """
    Regressão com valor conhecido.

    O MapBiomas registra 21,1 t MS/ha/ano (2024) e 21,8 (2023) neste imóvel.
    """
    estimate = estimate_annual_productivity(roi=covered_roi, year=2024)

    assert estimate.metric_type == "annual_dry_matter_productivity"
    assert estimate.unit_per_ha == "t_DM_ha_year"
    assert estimate.temporal_support == "annual"
    assert estimate.value_per_ha == pytest.approx(21.1, abs=1.5)
    assert estimate.raster_resolution_m == 30.0
    assert estimate.period_start == datetime.date(2024, 1, 1)
    assert estimate.period_end == datetime.date(2025, 1, 1)


def test_annual_total_is_the_per_hectare_value_integrated_by_pixel_area(covered_roi):
    """
    Requisito 2: o total sai de pixelArea(), não de multiplicador fixo.

    Total e média x área válida têm que bater dentro da tolerância numérica da
    redução; um multiplicador fixo por resolução erraria muito mais que isso.
    """
    estimate = estimate_annual_productivity(roi=covered_roi, year=2024)

    assert estimate.valid_area_ha is not None
    assert estimate.total_value is not None
    assert estimate.valid_area_ha <= _COVERED_AREA_HA * 1.1

    assert estimate.total_value == pytest.approx(
        estimate.value_per_ha * estimate.valid_area_ha, rel=0.05
    )
    # O fator 0,09 da implementação anterior errava a ordem de grandeza do total.
    assert estimate.total_value > estimate.value_per_ha


def test_annual_legend_values_are_not_rescaled(covered_roi):
    """Valores de pixel do MapBiomas já estão em t/ha e não podem ser multiplicados."""
    estimate = estimate_annual_productivity(roi=covered_roi, year=2024)

    assert estimate.conversion_factors == {"asset_scale": 1.0}
    assert 10.0 < estimate.value_per_ha < 35.0


# -----------------------------------------------------------------------------
# Fonte mensal: Time2Graze
# -----------------------------------------------------------------------------

def test_monthly_estimate_is_plausible_and_fully_documented(covered_roi, covered_mask):
    """Requisito 12: valores dentro da faixa agronômica, com metadados completos."""
    estimate = latest_monthly_productivity(roi=covered_roi, mask=covered_mask)

    if estimate is None:
        pytest.skip("Sem cobertura Time2Graze recente para o imóvel de teste.")

    assert estimate.metric_type == "monthly_dry_matter_productivity"
    assert estimate.unit_per_ha == "t_DM_ha_month"
    assert estimate.temporal_support == "monthly"
    # Produtividade mensal de pastagem tropical: décimos a poucos t MS/ha/mês.
    assert 0.0 <= estimate.value_per_ha <= 6.0
    assert estimate.raster_resolution_m == 10.0
    assert estimate.effective_mask_resolution_m == pytest.approx(30.0)
    assert estimate.valid_observation_fraction is not None
    assert estimate.lower_bound_per_ha < estimate.value_per_ha < estimate.upper_bound_per_ha
    # A escala tem que ser a do asset efetivamente escolhido: `cf` guarda 0,01 e
    # `prod` guarda 0,1, e a estimativa não pode misturar um com a escala do outro.
    scales = {contract.stored_scale for contract in T2G_UGPP_CONTRACTS}
    assert estimate.conversion_factors["asset_scale"] in scales
    matching = [
        contract for contract in T2G_UGPP_CONTRACTS
        if contract.producer_version == estimate.source_version
    ]
    assert len(matching) == 1, f"fonte '{estimate.source_version}' não bate com nenhum contrato"
    assert estimate.conversion_factors["asset_scale"] == matching[0].stored_scale
    assert "asset_scale_inferred" in estimate.quality_flags
    assert any("não representa" in item for item in estimate.limitations)


def test_monthly_total_uses_pixel_area(covered_roi, covered_mask):
    """Requisito 2 na fonte mensal."""
    estimate = latest_monthly_productivity(roi=covered_roi, mask=covered_mask)

    if estimate is None:
        pytest.skip("Sem cobertura Time2Graze recente para o imóvel de teste.")

    assert estimate.total_value == pytest.approx(
        estimate.value_per_ha * estimate.valid_area_ha, rel=0.05
    )
    # A máscara de pastagem recorta o imóvel: a área válida não pode excedê-lo.
    assert estimate.valid_area_ha <= _COVERED_AREA_HA * 1.1


def test_wet_season_is_more_productive_than_dry_season(covered_roi, covered_mask):
    """Sanidade agronômica: janeiro (águas) produz mais que agosto (seca)."""
    wet = estimate_monthly_productivity(
        roi=covered_roi, year=2026, month=1, mask=covered_mask,
        today=datetime.date(2026, 9, 21),
    )
    dry = estimate_monthly_productivity(
        roi=covered_roi, year=2025, month=8, mask=covered_mask,
        today=datetime.date(2026, 9, 21),
    )

    if wet is None or dry is None:
        pytest.skip("Sem cobertura Time2Graze para os dois meses comparados.")

    assert wet.value_per_ha > dry.value_per_ha


def test_january_period_crosses_the_year_boundary_correctly(covered_roi, covered_mask):
    """Requisito 3 no caminho real: janeiro acumula janeiro, não dezembro."""
    estimate = estimate_monthly_productivity(
        roi=covered_roi, year=2026, month=1, mask=covered_mask,
        today=datetime.date(2026, 9, 21),
    )

    if estimate is None:
        pytest.skip("Sem cobertura Time2Graze para janeiro de 2026.")

    assert estimate.period_start == datetime.date(2026, 1, 1)
    assert estimate.period_end == datetime.date(2026, 2, 1)
    assert estimate.period_days == 31
    assert "01/01/2026 a 31/01/2026" in estimate.to_report_block()


# -----------------------------------------------------------------------------
# Requisito 4: fallback explícito
# -----------------------------------------------------------------------------

def test_period_before_the_series_has_no_monthly_estimate(covered_roi, covered_mask):
    """
    Fallback explícito, não silencioso.

    A série mensal começa em 2025. Para um mês anterior a resposta correta é "não há
    estimativa mensal", nunca o valor anual do MapBiomas travestido de mensal.
    """
    estimate = estimate_monthly_productivity(
        roi=covered_roi, year=2024, month=6, mask=covered_mask,
        today=datetime.date(2026, 9, 21),
    )

    assert estimate is None


def test_missing_monthly_data_can_raise_with_an_explanatory_message(covered_roi, covered_mask):
    with pytest.raises(NoDataForPeriodError, match="Não há estimativa mensal"):
        estimate_monthly_productivity(
            roi=covered_roi, year=2024, month=6, mask=covered_mask,
            today=datetime.date(2026, 9, 21), raise_on_missing=True,
        )


def test_the_production_asset_extends_coverage_beyond_the_historical_one():
    """
    Os dois assets uGPP têm coberturas de tile diferentes.

    O imóvel de Silvânia não tem nenhuma cena no `cf`, mas tem no `prod`: manter os
    dois assets (cada um com a sua escala) cobre propriedades que um só não cobriria.
    """
    roi = _roi(_UNCOVERED_CAR)

    counts = {
        contract.producer_version: int(
            ee.ImageCollection(contract.asset_id).filterBounds(roi).size().getInfo()
        )
        for contract in T2G_UGPP_CONTRACTS
    }

    assert counts[T2G_UGPP_CF_CONTRACT.producer_version] == 0
    assert sum(counts.values()) > 0, "nenhum asset cobre o imóvel — teste desatualizado"


def test_property_covered_only_by_the_production_asset_uses_its_scale():
    """A estimativa carrega a escala do asset que a produziu, não a do outro."""
    roi = _roi(_UNCOVERED_CAR)
    mask = build_pasture_mask(roi=roi, strategy="official")

    estimate = estimate_monthly_productivity(
        roi=roi, year=2026, month=7, mask=mask, today=datetime.date(2026, 9, 21),
    )

    if estimate is None:
        pytest.skip("Sem cobertura do asset de produção para o imóvel/período.")

    matching = [
        contract for contract in T2G_UGPP_CONTRACTS
        if contract.producer_version == estimate.source_version
    ]
    assert len(matching) == 1
    assert estimate.conversion_factors["asset_scale"] == matching[0].stored_scale
    assert 0.0 <= estimate.value_per_ha <= 6.0


def test_annual_estimate_still_works_where_monthly_does_not():
    """A fonte anual cobre o Brasil todo; ela só não pode ser rotulada como mensal."""
    roi = _roi(_UNCOVERED_CAR)

    estimate = estimate_annual_productivity(roi=roi, year=2024)

    assert estimate.metric_type == "annual_dry_matter_productivity"
    assert estimate.temporal_support == "annual"
    assert estimate.value_per_ha > 0


def test_month_beyond_the_asset_coverage_returns_no_estimate(covered_roi, covered_mask):
    """A série Time2Graze termina antes do mês corrente; isso tem que aparecer."""
    period_start, _ = monthly_period(2026, 9, today=datetime.date(2026, 9, 21))
    assert period_start == datetime.date(2026, 9, 1)

    result = monthly_productivity_image(
        roi=covered_roi,
        period_start=datetime.date(2026, 9, 1),
        period_end=datetime.date(2026, 9, 21),
        mask=covered_mask,
    )

    if result is not None:
        pytest.skip("A cobertura Time2Graze avançou até setembro de 2026.")

    assert result is None


def test_known_bad_date_is_excluded_from_the_series(covered_roi, covered_mask):
    """
    O outlier de 2025-07-03 (média bruta ~10x o normal) não pode entrar na conta.
    """
    assert "2025-07-03" in T2G_UGPP_CF_CONTRACT.known_bad_dates

    estimate = estimate_monthly_productivity(
        roi=covered_roi, year=2025, month=7, mask=covered_mask,
        today=datetime.date(2026, 9, 21),
    )

    if estimate is None:
        pytest.skip("Sem cobertura Time2Graze para julho de 2025.")

    # Com o outlier dentro, julho/2025 saltaria para fora do envelope agronômico.
    assert estimate.value_per_ha < 6.0
