from typing import List
from pydantic import BaseModel, Field


class Value(BaseModel):
    value: float = Field(description="Valor numérico absoluto da medida.")
    unity: str = Field(description="Unidade de medida padronizada.")


class BiomassData(BaseModel):
    amount: Value = Field(description="Estimativa da massa biológica total acumulada na vegetação da área analisada.")


class AgeData(BaseModel):
    age: str = Field(
        description=(
            "A classificação do tempo de existência da pastagem (ex: '1 a 10 anos', '10 a 20 anos'). "
            "Representa há quanto tempo aquela área é identificada como pastagem contínua."
        )
    )
    amount: Value = Field(description="Área territorial coberta por este intervalo de idade específico.")


class VigorData(BaseModel):
    vigor: str = Field(
        description=(
            "Índice de saúde vegetativa e produtividade da pastagem (ex: 'Baixo', 'Médio', 'Alto')."
            "Avalia o estado biológico e a capacidade de suporte da vegetação."
        )
    )
    amount: Value = Field(description="Área territorial que apresenta este nível de vigor biológico.")


class LULCClassData(BaseModel):
    lulc_class: str = Field(
        description=(
            "Categoria de Uso e Cobertura da Terra (Land Use and Land Cover). "
            "Identifica o que existe na superfície, como diferentes tipos de culturas, florestas ou infraestrutura."
        )
    )
    amount: Value = Field(description="Área territorial ocupada por esta classe de cobertura/uso.")


class PastureStatsResult(BaseModel):
    """Consolidado de indicadores biofísicos e geográficos da área de pastagem. """
    biomass: BiomassData = Field(description="Dados de produtividade primária (biomassa), essenciais para cálculo de estoque de carbono e suporte de carga animal.")
    age: List[AgeData] = Field(description="Distribuição histórica da pastagem. Ajuda a identificar áreas recém-convertidas ou pastos degradados pelo tempo.")
    vigor: List[VigorData] = Field(description="Indicadores de performance vegetativa atual. Utilizado para identificar necessidade de reforma ou adubação.")
    lulc_class: List[LULCClassData] = Field(description="Mapeamento de uso do solo. Identifica se a área é puramente pastagem ou se possui integração com outras culturas e matas nativas.")