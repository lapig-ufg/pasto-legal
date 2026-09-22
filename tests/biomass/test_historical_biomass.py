"""
Testes da série histórica on-the-fly (issue #112).

A primeira metade é hermética (conversão, incerteza, chave de cache, gráfico);
a segunda toca o Earth Engine e exige `.env` com credenciais.

    PYTHONPATH=. .venv/bin/python -m pytest tests/biomass/test_historical_biomass.py -v
"""
import datetime
import json

from pathlib import Path

import pytest

from app.schemas.biomass_schemas import BiomassEstimate
from app.services.geospatial.biomass.biomass_charts import (
    render_historical_series_chart,
    series_table,
)
from app.services.geospatial.biomass.biomass_validation import (
    CARBON_TO_DRY_MATTER_IPCC,
    CARBON_TO_DRY_MATTER_MAPBIOMAS_BR,
    GPW_UGPP_HISTORICAL_CONTRACT,
    GRASS_LUE_MAX_GC_PER_MJ,
    T2G_UGPP_CF_CONTRACT,
    T2G_UGPP_PROD_CONTRACT,
)
from app.services.geospatial.biomass.historical_biomass import (
    HISTORICAL_MODEL_VERSION,
    historical_cache_key,
    historical_conversion_factors,
    historical_uncertainty_bounds,
    gpp_to_dry_matter_t_ha,
    utm_crs_for,
)


_ROOT = Path(__file__).resolve().parents[2]
_MOCK_PATH = _ROOT / "app/utils/mocks/new_property_mock.json"

_COVERED_CAR = "GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0"


def _annual(year: int, value: float, **overrides) -> BiomassEstimate:
    lower, upper = historical_uncertainty_bounds(value)
    kwargs = dict(
        metric_type="annual_dry_matter_productivity",
        source="Global Pasture Watch uGPP histórico (on-the-fly)",
        source_version="ggpp-30m v1 / ugpp_m",
        period_start=datetime.date(year, 1, 1),
        period_end=datetime.date(year + 1, 1, 1),
        temporal_support="annual",
        value_per_ha=value,
        total_value=value * 17.7,
        unit_per_ha="t_DM_ha_year",
        total_unit="t_DM_year",
        raster_resolution_m=30.0,
        effective_mask_resolution_m=30.0,
        pasture_mask_source="Global Pasture Watch",
        pasture_mask_reference_year=2024,
        valid_area_ha=17.7,
        lower_bound_per_ha=lower,
        upper_bound_per_ha=upper,
        uncertainty_method="faixa de CUE",
        conversion_factors=historical_conversion_factors(),
        model_version=HISTORICAL_MODEL_VERSION,
    )
    kwargs.update(overrides)
    return BiomassEstimate(**kwargs)


# -----------------------------------------------------------------------------
# Conversão: pixel sintético e fatores nomeados
# -----------------------------------------------------------------------------

def test_synthetic_pixel_converts_ugpp_to_dry_matter():
    """
    Reproduz o `DRY_BIOMASS_FACTOR` do script oficial GPW/LAPIG.

    1000 x escala 1,0 x LUEmax 0,50 x 2,3 (MapBiomas BR) x 0,01 = 11,5 t MS/ha/ano.
    """
    assert gpp_to_dry_matter_t_ha(1000.0) == pytest.approx(11.5, abs=1e-9)


def test_synthetic_pixel_with_the_ipcc_variant():
    """A variante do IPCC (2,7) é a outra opção documentada no script."""
    assert gpp_to_dry_matter_t_ha(
        1000.0, carbon_to_dry_matter=CARBON_TO_DRY_MATTER_IPCC
    ) == pytest.approx(13.5, abs=1e-9)


def test_conversion_reproduces_the_official_script_factor():
    """
    O fator efetivo tem que ser idêntico ao do script de referência:
    DRY_BIOMASS_FACTOR = GRASS_LUEMAX_FACTOR * IPCC_FACTOR * UNIT_CONVERSION.
    """
    factors = historical_conversion_factors()
    efetivo = (
        factors["asset_scale"] * factors["grass_fraction_or_lue"]
        * factors["carbon_to_dry_matter"] * factors["unit_conversion"]
    )

    assert efetivo == pytest.approx(0.50 * 2.3 * 0.01)
    assert factors["grass_fraction_or_lue"] == GRASS_LUE_MAX_GC_PER_MJ


def test_conversion_is_linear_in_the_signal():
    assert gpp_to_dry_matter_t_ha(2000.0) == pytest.approx(gpp_to_dry_matter_t_ha(1000.0) * 2)
    assert gpp_to_dry_matter_t_ha(0.0) == 0.0


def test_lue_is_mandatory_in_the_chain():
    """
    Sem o LUEmax a conversão superestima em 2x.

    A banda `gc_m2` não é carbono já convertido: o LUEmax ainda precisa ser
    aplicado, como faz o script oficial.
    """
    com_lue = gpp_to_dry_matter_t_ha(1886.2)
    sem_lue = gpp_to_dry_matter_t_ha(1886.2, lue=1.0)

    assert sem_lue / com_lue == pytest.approx(1 / GRASS_LUE_MAX_GC_PER_MJ)
    assert sem_lue > 40.0
    # Com o LUEmax o valor fica junto do MapBiomas medido no imóvel (21,08).
    assert com_lue == pytest.approx(21.69, abs=0.1)


def test_the_global_mod17_lue_does_not_apply_to_brazil():
    """
    O script traz LUEmax 0,86 (MOD17A2, global) e 0,50 (Urochloa, Brasil).

    Para os imóveis de referência o global quase dobra o valor do MapBiomas —
    por isso o padrão aqui é o brasileiro.
    """
    brasil = gpp_to_dry_matter_t_ha(1886.2)
    global_mod17 = gpp_to_dry_matter_t_ha(1886.2, lue=0.86)

    assert global_mod17 / brasil == pytest.approx(0.86 / 0.50)
    assert global_mod17 > 35.0


def test_conversion_factors_are_all_named():
    factors = historical_conversion_factors()

    assert set(factors) == {
        "asset_scale", "grass_fraction_or_lue", "carbon_to_dry_matter", "unit_conversion",
    }
    assert factors["asset_scale"] == 1.0, "o produto histórico não tem escala a aplicar"
    assert factors["carbon_to_dry_matter"] == CARBON_TO_DRY_MATTER_MAPBIOMAS_BR


def test_the_historical_chain_matches_the_monthly_one():
    """
    As duas fontes uGPP usam a mesma estrutura de fatores.

    Antes desta correção o histórico usava uma cadeia própria (eficiência do uso do
    carbono), inconsistente com o mensal sem motivo.
    """
    from app.services.geospatial.biomass.biomass_productivity import (
        dry_matter_conversion_factors,
    )

    mensal = dry_matter_conversion_factors()
    historico = historical_conversion_factors()

    assert mensal["grass_fraction_or_lue"] == historico["grass_fraction_or_lue"]
    assert mensal["unit_conversion"] == historico["unit_conversion"]


def test_uncertainty_bounds_span_the_two_documented_variants():
    """O intervalo é a distância entre o fator 2,3 e o 2,7, ambos do script oficial."""
    lower, upper = historical_uncertainty_bounds(21.69)

    assert lower == pytest.approx(21.69)
    assert upper == pytest.approx(21.69 * CARBON_TO_DRY_MATTER_IPCC / CARBON_TO_DRY_MATTER_MAPBIOMAS_BR)
    assert lower <= 21.69 <= upper


def test_the_default_variant_agrees_with_mapbiomas():
    """
    Com o fator brasileiro a estimativa fica a -2,4% do MapBiomas em média.

    No imóvel de referência em 2024: 21,69 estimado contra 21,08 do MapBiomas.
    """
    estimado = gpp_to_dry_matter_t_ha(1886.2)

    assert abs(estimado - 21.08) / 21.08 < 0.05


# -----------------------------------------------------------------------------
# Contratos: os dois assets uGPP têm escalas diferentes
# -----------------------------------------------------------------------------

def test_the_two_t2g_assets_have_different_scales():
    """
    Regressão da troca de asset feita no develop.

    `ugpp_prod_10m_v1` armazena valores ~10x menores que `ugpp_cf_10m_v1`; trocar
    um pelo outro sem trocar a escala erra a estimativa em 10x.
    """
    assert T2G_UGPP_CF_CONTRACT.stored_scale == 0.01
    assert T2G_UGPP_PROD_CONTRACT.stored_scale == 0.1
    assert T2G_UGPP_PROD_CONTRACT.stored_scale == T2G_UGPP_CF_CONTRACT.stored_scale * 10

    assert T2G_UGPP_CF_CONTRACT.asset_id != T2G_UGPP_PROD_CONTRACT.asset_id
    for contract in (T2G_UGPP_CF_CONTRACT, T2G_UGPP_PROD_CONTRACT):
        assert contract.evidence, f"{contract.asset_id} sem evidência da escala"


def test_historical_contract_declares_annual_support_and_thirty_metres():
    assert GPW_UGPP_HISTORICAL_CONTRACT.temporal_support == "annual"
    assert GPW_UGPP_HISTORICAL_CONTRACT.nominal_resolution_m == 30.0
    assert GPW_UGPP_HISTORICAL_CONTRACT.band == "gc_m2"
    # A banda chama-se `gc_m2` mas guarda uGPP: o LUEmax ainda precisa ser aplicado.
    assert "uGPP" in GPW_UGPP_HISTORICAL_CONTRACT.native_unit
    assert "LUEmax" in GPW_UGPP_HISTORICAL_CONTRACT.native_unit


# -----------------------------------------------------------------------------
# Reprodutibilidade da chave de exportação
# -----------------------------------------------------------------------------

class _FakeMask:
    def __init__(self, signature: str = "GPW|v1-1|2024|30|official"):
        self._signature = signature

    def signature(self) -> str:
        return self._signature


def _key(**overrides) -> str:
    kwargs = dict(
        feature_id=_COVERED_CAR, start_year=2000, end_year=2024,
        mask=_FakeMask(), carbon_to_dry_matter=CARBON_TO_DRY_MATTER_MAPBIOMAS_BR, scale=30.0,
    )
    kwargs.update(overrides)
    return historical_cache_key(**kwargs)


def test_export_key_is_deterministic():
    assert _key() == _key()


def test_export_key_changes_with_every_input_that_changes_the_result():
    assert _key() != _key(start_year=2010)
    assert _key() != _key(end_year=2020)
    assert _key() != _key(carbon_to_dry_matter=CARBON_TO_DRY_MATTER_IPCC)
    assert _key() != _key(scale=10.0)
    assert _key() != _key(mask=_FakeMask("GPW|v1-1|2023|30|official"))
    assert _key() != _key(feature_id="OUTRO-CAR")


def test_export_key_is_filesystem_safe():
    key = _key(feature_id="GO/123, 456")

    for forbidden in ("/", ",", " "):
        assert forbidden not in key


def test_utm_zone_is_derived_from_the_longitude():
    class _FakeGeometry:
        def __init__(self, lon, lat):
            self._coords = [lon, lat]

        def centroid(self, _maxError):
            return self

        def coordinates(self):
            return self

        def getInfo(self):
            return self._coords

    # Goiás (-50,6; -16,4) -> zona 22 sul.
    assert utm_crs_for(_FakeGeometry(-50.6, -16.4)) == "EPSG:32722"
    # Hemisfério norte usa o prefixo 326.
    assert utm_crs_for(_FakeGeometry(-50.6, 10.0)) == "EPSG:32622"


# -----------------------------------------------------------------------------
# Gráfico e tabela
# -----------------------------------------------------------------------------

def test_chart_renders_from_a_series():
    pytest.importorskip("matplotlib")

    series = [_annual(year, 22.0 + (year % 5) * 0.4) for year in range(2015, 2025)]

    image = render_historical_series_chart(series)

    assert image.width > 300 and image.height > 200


def test_chart_accepts_a_reference_line():
    pytest.importorskip("matplotlib")

    series = [_annual(year, 22.0) for year in range(2015, 2025)]
    reference = {year: 21.0 for year in range(2015, 2025)}

    image = render_historical_series_chart(series, reference_values=reference)

    assert image.width > 300


def test_chart_refuses_a_series_without_values():
    pytest.importorskip("matplotlib")

    empty = [_annual(2020, 22.0).model_copy(update={"value_per_ha": None})]

    with pytest.raises(ValueError, match="Não há estimativa com valor"):
        render_historical_series_chart(empty)


def test_series_table_carries_the_unit_in_the_header():
    rows = series_table([_annual(2023, 22.0), _annual(2024, 21.0)])

    assert rows[0][0] == "Ano"
    assert "t MS/ha/ano" in rows[0][1]
    assert rows[1][0] == "2023"
    assert rows[2][0] == "2024"
    assert len(rows) == 3


def test_series_table_is_sorted_chronologically():
    rows = series_table([_annual(2024, 21.0), _annual(2020, 25.0), _annual(2022, 23.0)])

    assert [row[0] for row in rows[1:]] == ["2020", "2022", "2024"]


# -----------------------------------------------------------------------------
# Integração real com o Earth Engine
# -----------------------------------------------------------------------------

@pytest.mark.integration
def test_historical_series_matches_the_known_property(covered_roi_fixture=None):
    import ee

    from app.services.geospatial.biomass.historical_biomass import historical_series
    from app.services.geospatial.biomass.pasture_mask import build_pasture_mask

    features = json.loads(_MOCK_PATH.read_text())["features"]
    feature = next(item for item in features if item["properties"]["codigo"] == _COVERED_CAR)
    roi = ee.Geometry.MultiPolygon([feature["geometry"]["coordinates"]])

    mask = build_pasture_mask(roi=roi, strategy="official")
    series = historical_series(roi=roi, start_year=2020, end_year=2024, mask=mask)

    assert len(series) == 5
    assert [item.period_start.year for item in series] == [2020, 2021, 2022, 2023, 2024]

    mapbiomas_asset = ee.Image(
        "projects/mapbiomas-public/assets/brazil/lulc/collection10/"
        "mapbiomas_brazil_collection10_pasture_biomass_v2"
    )

    for estimate in series:
        assert estimate.metric_type == "annual_dry_matter_productivity"
        assert estimate.unit_per_ha == "t_DM_ha_year"
        assert estimate.temporal_support == "annual"
        assert estimate.raster_resolution_m == 30.0
        assert estimate.lower_bound_per_ha <= estimate.value_per_ha <= estimate.upper_bound_per_ha

        # Regressão contra fonte independente: com o fator brasileiro (2,3) a
        # estimativa fica a poucos por cento do MapBiomas neste imóvel. Uma
        # duplicação ou omissão de fator na cadeia sai desta faixa na hora.
        year = estimate.period_start.year
        reference = mapbiomas_asset.select(f"biomass_{year}").reduceRegion(
            reducer=ee.Reducer.mean(), geometry=roi, scale=30, maxPixels=1e13,
        ).getInfo().get(f"biomass_{year}")

        assert reference is not None
        assert estimate.value_per_ha == pytest.approx(reference, rel=0.10), (
            f"{year}: {estimate.value_per_ha:.2f} vs MapBiomas {reference:.2f}"
        )


@pytest.mark.integration
def test_pixel_export_round_trips_through_zarr(tmp_path, monkeypatch):
    import ee
    import numpy as np

    from app.services.geospatial.biomass import historical_cache
    from app.services.geospatial.biomass.historical_biomass import export_historical_series
    from app.services.geospatial.biomass.pasture_mask import build_pasture_mask

    monkeypatch.setattr(historical_cache, "_LOCAL_CACHE_DIR", tmp_path)
    monkeypatch.setattr(historical_cache, "uses_s3", lambda: False)

    features = json.loads(_MOCK_PATH.read_text())["features"]
    feature = next(item for item in features if item["properties"]["codigo"] == _COVERED_CAR)
    roi = ee.Geometry.MultiPolygon([feature["geometry"]["coordinates"]])

    mask = build_pasture_mask(roi=roi, strategy="official")
    result = export_historical_series(
        roi=roi, feature_id=_COVERED_CAR, start_year=2023, end_year=2024, mask=mask,
    )

    assert result["cached"] is False
    assert result["years"] == [2023, 2024]
    assert Path(result["path"]).exists()

    dataset = result["dataset"]
    values = dataset["dm_t_ha_year"].values
    mask_value = dataset.attrs["mask_value"]

    # Pixel fora da pastagem carrega o sentinela, nunca zero: zero significaria
    # produtividade nula de verdade.
    assert (values == mask_value).any(), "nenhum pixel mascarado — o sentinela sumiu"
    valid = values[values != mask_value]
    assert valid.size > 0
    assert not (valid == 0).any(), "pixel válido com zero espúrio"

    # Os valores guardados são t MS/ha/ano x 1000.
    as_t_ha = valid * dataset.attrs["value_scale_factor"]
    assert 10.0 < float(np.mean(as_t_ha)) < 35.0

    # Proveniência completa dentro do próprio arquivo.
    for key in (
        "metric_type", "unit_per_ha", "value_scale_factor", "mask_value",
        "source_asset", "raster_resolution_m", "effective_mask_resolution_m",
        "pasture_mask_source", "model_version", "factor_carbon_to_dry_matter",
    ):
        assert key in dataset.attrs, f"atributo de proveniência ausente: {key}"

    # Segunda chamada reaproveita a exportação.
    again = export_historical_series(
        roi=roi, feature_id=_COVERED_CAR, start_year=2023, end_year=2024, mask=mask,
    )
    assert again["cached"] is True
    assert again["n_pixels"] == result["n_pixels"]


@pytest.mark.integration
def test_pixel_mean_matches_the_aggregate_estimate():
    """O que sai no zarr e o que sai no resumo têm que ser o mesmo número."""
    import ee
    import numpy as np

    from app.services.geospatial.biomass.historical_biomass import (
        estimate_historical_productivity,
        historical_pixel_dataset,
    )
    from app.services.geospatial.biomass.pasture_mask import build_pasture_mask

    features = json.loads(_MOCK_PATH.read_text())["features"]
    feature = next(item for item in features if item["properties"]["codigo"] == _COVERED_CAR)
    roi = ee.Geometry.MultiPolygon([feature["geometry"]["coordinates"]])

    mask = build_pasture_mask(roi=roi, strategy="official")

    estimate = estimate_historical_productivity(roi=roi, year=2024, mask=mask)
    dataset = historical_pixel_dataset(roi=roi, start_year=2024, end_year=2024, mask=mask)

    values = dataset["dm_t_ha_year"].values
    valid = values[values != dataset.attrs["mask_value"]]
    pixel_mean = float(np.mean(valid)) * dataset.attrs["value_scale_factor"]

    assert pixel_mean == pytest.approx(estimate.value_per_ha, rel=0.05)
