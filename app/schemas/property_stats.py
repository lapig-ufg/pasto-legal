from typing import List, Optional
from pydantic import BaseModel, Field


class Value(BaseModel):
    value: float = Field(..., description="Valor numérico absoluto da medida.")
    unity: str = Field(..., description="Unidade de medida padronizada.")

    def __str__(self) -> str:
        return f"{self.value} {self.unity}"


class BiomassStats(BaseModel):
    observation_year: int = Field(..., description="Ano de referência.")
    amount: Value = Field(..., description="Estimativa da massa biológica total acumulada na vegetação da área analisada.")

    def __str__(self) -> str:
        return (
            f"- Ano de Referência: {self.observation_year}\n"
            f"- Estimativa de Massa Biológica Acumulada na Vegetação: {self.amount}"
        )


class AgeData(BaseModel):
    age: str = Field(..., description="A classificação do tempo de existência da pastagem.")
    amount: Value = Field(..., description="Área territorial coberta por este intervalo de idade específico.")

    def __str__(self) -> str:
        return f"  * Faixa de idade contínua '{self.age}': {self.amount} de área coberta."


class AgeStats(BaseModel):
    observation_year: int = Field(..., description="Ano de referência.")
    data: List[AgeData] = Field(..., description="Grupos de idades de pastagens.")

    def __str__(self) -> str:
        linhas_dados = "\n".join(str(item) for item in self.data)
        return (
            f"- Ano de Referência: {self.observation_year}\n"
            f"- Distribuição da área territorial por tempo de existência da pastagem:\n{linhas_dados}"
        )


class VigorData(BaseModel):
    vigor: str = Field(..., description="Índice de saúde vegetativa e produtividade da pastagem.")
    amount: Value = Field(..., description="Área territorial que apresenta este nível de vigor biológico.")

    def __str__(self) -> str:
        return f"  * Nível de vigor '{self.vigor}': {self.amount} de área territorial apresentando esta condição."


class VigorStats(BaseModel):
    observation_year: int = Field(..., description="Ano de referência.")
    data: List[VigorData] = Field(..., description="Classes de vigor de pastagem.")

    def __str__(self) -> str:
        linhas_dados = "\n".join(str(item) for item in self.data)
        return (
            f"- Ano de Referência: {self.observation_year}\n"
            f"- Desempenho da performance vegetativa e vigor biológico atual:\n{linhas_dados}"
        )


class LULCData(BaseModel):
    lulc_class: str = Field(..., description="Categoria de Uso e Cobertura da Terra (Land Use and Land Cover).")
    amount: Value = Field(..., description="Área territorial ocupada pela classe de cobertura/uso.")

    def __str__(self) -> str:
        return f"  * Classe de uso/cobertura '{self.lulc_class}': {self.amount} ocupados."


class LULCStats(BaseModel):
    observation_year: int = Field(..., description="Ano de referência.")
    data: List[LULCData] = Field(..., description="Classes de uso e cobertura presentes na propriedade.")

    def __str__(self) -> str:
        linhas_dados = "\n".join(str(item) for item in self.data)
        return (
            f"- Ano de Referência: {self.observation_year}\n"
            f"- Mapeamento detalhado de Uso e Cobertura da Terra (LULC):\n{linhas_dados}"
        )


class PastureStats(BaseModel):
    biomass_stats: Optional[BiomassStats] = Field(None, description="Dados de produtividade primária (biomassa).")
    age_stats: Optional[AgeStats] = Field(None, description="Distribuição histórica da pastagem.")
    vigor_stats: Optional[VigorStats] = Field(None, description="Indicadores de performance vegetativa atual.")
    lulc_stats: Optional[LULCStats] = Field(None, description="Mapeamento de uso do solo.")

    def __str__(self) -> str:
        sections = ["# RELATÓRIO AGROAMBIENTAL: ESTATÍSTICAS E ANÁLISE DE PASTAGENS"]
        sections.append("Este relatório descreve o estado atual, histórico e biológico das áreas monitoradas.\n")
        
        if self.biomass_stats:
            sections.append("## 1. Produtividade Primária e Estoque de Carbono (Biomassa)")
            sections.append(str(self.biomass_stats))
            sections.append("---")
            
        if self.age_stats:
            sections.append("## 2. Histórico, Dinâmica Temporal e Idade da Pastagem")
            sections.append(str(self.age_stats))
            sections.append("---")
            
        if self.vigor_stats:
            sections.append("## 3. Qualidade Biológica e Performance Vegetativa Atual (Vigor)")
            sections.append(str(self.vigor_stats))
            sections.append("---")
            
        if self.lulc_stats:
            sections.append("## 4. Cobertura do Solo e Integração de Paisagem (LULC)")
            sections.append(str(self.lulc_stats))
            sections.append("---")
            
        if sections[-1] == "---":
            sections.pop()
            
        return "\n".join(sections)


class TopographicStats(BaseModel):
    elevation: Value = Field(
        ...,
        description="Altitude média do terreno em metros."
    )
    slope: Value = Field(
        ...,
        description="Declividade média do terreno em graus."
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
    list_soil_texture_stats: Optional[List[TopographicStats]] = Field(
        description="Mapeamento de textura de solo.",
        default_factory=list
    )