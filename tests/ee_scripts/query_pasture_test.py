import pytest
from pydantic import ValidationError

from domain.schemas.property_stats import AgeData, AgeStats, LULCData, LULCStats, VigorData, VigorStats
from domain.services.geospatial.gee import BiomassStats, PastureStats, PropertyStats, Value


def test_value_model_creation():
    val = Value(value=150.5, unity="hectares")
    assert val.value == 150.5
    assert val.unity == "hectares"


def test_value_model_validation_error():
    with pytest.raises(ValidationError):
        Value(value="cento e cinquenta", unity="hectares")


def test_biomass_data_model():
    biomass = BiomassStats(observation_year=2025, period="mensal", amount=Value(value=2000.0, unity="toneladas"))
    assert biomass.amount.value == 2000.0
    assert biomass.period == "mensal"


def test_biomass_period_must_be_monthly_or_annual():
    with pytest.raises(ValidationError):
        BiomassStats(observation_year=2025, period="semanal", amount=Value(value=1.0, unity="toneladas"))


def test_pasture_stats_result_composition():
    pasture = PastureStats(
        biomass_stats=BiomassStats(observation_year=2025, period="anual", amount=Value(value=550.2, unity="toneladas")),
        age_stats=AgeStats(observation_year=2024, data=[AgeData(age="1 a 10 anos", amount=Value(value=100.0, unity="hectares"))]),
        vigor_stats=VigorStats(observation_year=2024, data=[VigorData(vigor="Alto", amount=Value(value=120.0, unity="hectares"))]),
        lulc_stats=LULCStats(observation_year=2024, data=[LULCData(lulc_class="Pastagem", amount=Value(value=150.0, unity="hectares"))]),
    )
    result = PropertyStats(car_code="GO-1", list_pasture_stats=[pasture])

    assert result.list_pasture_stats[0].biomass_stats.amount.value == 550.2
    assert result.list_pasture_stats[0].age_stats.data[0].age == "1 a 10 anos"
    assert "Pastagem" in str(pasture)
