from typing import List, Optional
from pydantic import BaseModel, Field


class Value(BaseModel):
    value: float = Field(
        ...,
        description="Valor numérico absoluto da medida."
    )

    unity: str = Field(
        ...,
        description="Unidade de medida padronizada."
    )


class BiomassData(BaseModel):
    amount: Value = Field(
        ...,
        description="Estimativa da massa biológica total acumulada na vegetação da área analisada."
    )


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
        ...,
        description="Índice de saúde vegetativa e produtividade da pastagem (ex: 'Baixo', 'Médio', 'Alto')."
    )

    amount: Value = Field(
        ...,
        description="Área territorial que apresenta este nível de vigor biológico."
    )


class LULCClassData(BaseModel):
    lulc_class: str = Field(
        ...,
        description="Categoria de Uso e Cobertura da Terra (Land Use and Land Cover)."
    )

    amount: Value = Field(
        ...,
        description="Área territorial ocupada pela classe de cobertura/uso."
    )


class PastureStats(BaseModel):
    year: int = Field(
        description="Ano da estatística."
    )
        
    biomass: Optional[BiomassData] = Field(
        description="Dados de produtividade primária (biomassa), essenciais para cálculo de estoque de carbono e suporte de carga animal."
    )

    age: Optional[List[AgeData]] = Field(
        description="Distribuição histórica da pastagem. Ajuda a identificar áreas recém-convertidas ou pastos degradados pelo tempo.",
        default_factory=list
    )

    vigor: Optional[List[VigorData]] = Field(
        description="Indicadores de performance vegetativa atual. Utilizado para identificar necessidade de reforma ou adubação.",
        default_factory=list
    )

    lulc_class: Optional[List[LULCClassData]] = Field(
        description="Mapeamento de uso do solo. Identifica se a área é puramente pastagem ou se possui integração com outras culturas e matas nativas.",
        default_factory=list
    )


class SoilTextureData(BaseModel):
    texture: str = Field(
        ...,
        description="Classe de textura de solo predominante."
    )

    depth: str = Field(
        ...,
        description="Profundida da textura de solo."
    )


class SoilTextureStats(BaseModel):
    year: int = Field(
        description="Ano da estatística."
    )

    textures: List[SoilTextureData] = Field(
        ...,
        description="Mapeamento de textura de solo."
    )


class PropertyStats(BaseModel):
    car_code: str = Field(
        ...,
        description="Identificador único da propriedade rural.",
    )

    list_pasture_stats: Optional[List[PastureStats]] = Field(
        description="Indicadores biofísicos e geográficos da área de pastagem.",
        default_factory=list
    )

    list_soil_texture_stats: Optional[List[SoilTextureStats]] = Field(
        description="Mapeamento de textura de solo.",
        default_factory=list
    )