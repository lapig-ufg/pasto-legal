import pytest
from pydantic import ValidationError

# Substitua 'app.tools.pasture' pelo caminho real de importação no seu projeto
from app.utils.scripts.gee_scripts import (
    Value, 
    BiomassData, 
    AgeData, 
    VigorData, 
    LULCClassData, 
    PastureStatsResult
)

def test_value_model_creation():
    """Testa se o modelo Value base é criado corretamente com tipos válidos."""
    val = Value(value=150.5, unity="hectares")
    assert val.value == 150.5
    assert val.unity == "hectares"

def test_value_model_validation_error():
    """Testa se o Pydantic levanta erro ao passar um tipo de dado incorreto (ex: string no lugar de float)."""
    with pytest.raises(ValidationError):
        # Passando um texto em vez de um número (float)
        Value(value="cento e cinquenta", unity="hectares")

def test_biomass_data_model():
    """Testa o modelo de Biomassa (que contém um Value aninhado)."""
    biomass = BiomassData(amount=Value(value=2000.0, unity="toneladas"))
    assert biomass.amount.value == 2000.0
    assert biomass.amount.unity == "toneladas"

def test_pasture_stats_result_composition():
    """Testa se o modelo principal compila todos os dados e listas corretamente."""
    
    # Mockando os dados que viriam do Earth Engine / refatoração
    biomass = BiomassData(amount=Value(value=550.2, unity="toneladas"))
    
    age_list = [
        AgeData(age="1 a 10 anos", amount=Value(value=100.0, unity="hectares")),
        AgeData(age="10 a 20 anos", amount=Value(value=50.0, unity="hectares"))
    ]
    
    vigor_list = [
        VigorData(vigor="Alto", amount=Value(value=120.0, unity="hectares")),
        VigorData(vigor="Baixo", amount=Value(value=30.0, unity="hectares"))
    ]
    
    lulc_list = [
        LULCClassData(lulc_class="Pastagem", amount=Value(value=150.0, unity="hectares"))
    ]

    # Instanciando o modelo consolidado
    result = PastureStatsResult(
        biomass=biomass,
        age=age_list,
        vigor=vigor_list,
        lulc_class=lulc_list
    )

    # Asserções para garantir que a estrutura final está intacta
    assert result.biomass.amount.value == 550.2
    assert len(result.age) == 2
    assert result.age[0].age == "1 a 10 anos"
    assert result.vigor[1].vigor == "Baixo"
    assert result.lulc_class[0].amount.unity == "hectares"