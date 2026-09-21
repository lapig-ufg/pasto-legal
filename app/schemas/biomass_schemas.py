"""Modelo de dados das estimativas de biomassa de pastagem.

Este módulo existe para impedir que quatro conceitos agronomicamente distintos
continuem sendo tratados como sinônimos:

    1. `monthly_dry_matter_productivity`  - t MS/ha/mês  (quanto o pasto PRODUZIU no mês)
    2. `annual_dry_matter_productivity`   - t MS/ha/ano  (quanto o pasto PRODUZIU no ano)
    3. `standing_dry_matter_biomass`      - t MS/ha      (quanto está EM PÉ agora)
    4. `available_forage`                 - t MS/ha      (quanto pode ser PASTEJADO)

Produtividade (1 e 2) é fluxo; biomassa em pé (3) é estoque; forragem disponível (4)
é o estoque menos o resíduo mínimo, vezes a taxa de utilização. Converter GPP/uGPP
em matéria seca produz (1) ou (2) — nunca (3) nem (4).

Toda estimativa carrega obrigatoriamente fonte, período, unidade, resolução do
raster, resolução efetiva da máscara, cobertura válida, fatores de conversão,
versão do modelo e flags de qualidade, de modo que nenhum número possa circular
pela interface, pelo boletim ou pelo LLM sem o seu contexto.
"""

from datetime import date
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


MetricType = Literal[
    "monthly_dry_matter_productivity",
    "annual_dry_matter_productivity",
    "standing_dry_matter_biomass",
    "available_forage",
]

TemporalSupport = Literal["monthly", "annual", "instantaneous"]

# Unidade canônica de cada métrica. Qualquer divergência é erro de validação:
# é este mapa que impede "t MS/ha/mês" de ser rotulado como "t MS/ha".
METRIC_UNITS: Dict[str, tuple] = {
    "monthly_dry_matter_productivity": ("t_DM_ha_month", "t_DM_month"),
    "annual_dry_matter_productivity": ("t_DM_ha_year", "t_DM_year"),
    "standing_dry_matter_biomass": ("t_DM_ha", "t_DM"),
    "available_forage": ("t_DM_ha", "t_DM"),
}

# Suporte temporal exigido por métrica.
METRIC_TEMPORAL_SUPPORT: Dict[str, str] = {
    "monthly_dry_matter_productivity": "monthly",
    "annual_dry_matter_productivity": "annual",
    "standing_dry_matter_biomass": "instantaneous",
    "available_forage": "instantaneous",
}

# Rótulos em PT-BR usados na interface, no boletim e nas legendas dos mapas.
METRIC_LABELS: Dict[str, str] = {
    "monthly_dry_matter_productivity": "Produtividade mensal de matéria seca estimada",
    "annual_dry_matter_productivity": "Produtividade anual de matéria seca estimada",
    "standing_dry_matter_biomass": "Biomassa em pé estimada",
    "available_forage": "Forragem disponível para pastejo",
}

# Unidades em PT-BR para exibição (as unidades canônicas acima são de máquina).
UNIT_LABELS: Dict[str, str] = {
    "t_DM_ha_month": "t MS/ha/mês",
    "t_DM_ha_year": "t MS/ha/ano",
    "t_DM_ha": "t MS/ha",
    "t_DM_month": "t MS no mês",
    "t_DM_year": "t MS no ano",
    "t_DM": "t MS",
}


class PastureMaskMetadata(BaseModel):
    """
    Metadados obrigatórios da máscara de pastagem usada para recortar a estimativa.

    A máscara é o que define a resolução EFETIVA da análise: não adianta o produto
    ser 10 m se a máscara que o limita é de 30 m.
    """
    source: str = Field(..., description="Identificador do produto usado como máscara.")
    source_version: Optional[str] = Field(None, description="Versão/coleção do produto de máscara.")
    reference_year: Optional[int] = Field(None, description="Ano de referência do mapeamento da máscara.")
    resolution_m: float = Field(..., description="Resolução nominal da máscara, em metros.")
    classifier_version: Optional[str] = Field(None, description="Versão do classificador quando a máscara é on-the-fly.")
    pasture_area_ha: Optional[float] = Field(None, description="Área classificada como pastagem, em hectares.")
    property_area_ha: Optional[float] = Field(None, description="Área total da feição analisada, em hectares.")
    pasture_fraction: Optional[float] = Field(None, description="Fração da feição considerada pastagem (0-1).")
    uncertain_pixel_fraction: Optional[float] = Field(None, description="Fração de pixels de confiança baixa (0-1).")
    disagreement_fraction: Optional[float] = Field(None, description="Fração de pixels em que os classificadores divergem (0-1).")
    strategy: str = Field("official", description="Estratégia da máscara: 'official', 'on_the_fly' ou 'hybrid'.")

    def __str__(self) -> str:
        parts = [f"{self.source}"]
        if self.source_version:
            parts.append(f"v{self.source_version}")
        parts.append(f"{self.resolution_m:g} m")
        if self.reference_year:
            parts.append(f"referência {self.reference_year}")
        return ", ".join(parts)


class BiomassEstimate(BaseModel):
    """
    Uma estimativa de biomassa/produtividade com toda a sua proveniência.

    Nenhum campo de metadado é opcional por conveniência: `source`, `period_*`,
    `unit_*`, `raster_resolution_m`, `pasture_mask_source`, `conversion_factors`
    e `model_version` são obrigatórios justamente para que a estimativa não possa
    ser exibida sem contexto.
    """
    metric_type: MetricType = Field(..., description="Conceito agronômico que este número representa.")

    source: str = Field(..., description="Produto/fonte de dados de origem.")
    source_version: Optional[str] = Field(None, description="Versão do produto de origem.")

    period_start: date = Field(..., description="Início do período coberto (inclusivo).")
    period_end: date = Field(..., description="Fim do período coberto (exclusivo).")
    temporal_support: TemporalSupport = Field(..., description="Suporte temporal do dado.")

    value_per_ha: Optional[float] = Field(None, description="Valor médio por hectare na área válida.")
    total_value: Optional[float] = Field(None, description="Valor total na área válida (integrado por pixelArea).")

    unit_per_ha: str = Field(..., description="Unidade canônica do valor por hectare.")
    total_unit: str = Field(..., description="Unidade canônica do valor total.")

    raster_resolution_m: float = Field(..., description="Resolução nativa do raster da fonte, em metros.")
    effective_mask_resolution_m: Optional[float] = Field(None, description="Resolução efetiva imposta pela máscara, em metros.")
    pasture_mask_source: str = Field(..., description="Fonte da máscara de pastagem.")
    pasture_mask_reference_year: Optional[int] = Field(None, description="Ano de referência da máscara de pastagem.")
    pasture_mask: Optional[PastureMaskMetadata] = Field(None, description="Metadados completos da máscara.")

    valid_area_ha: Optional[float] = Field(None, description="Área com observação válida, em hectares.")
    valid_observation_fraction: Optional[float] = Field(None, description="Fração de observações válidas no período (0-1).")

    lower_bound_per_ha: Optional[float] = Field(None, description="Limite inferior do intervalo de incerteza, por hectare.")
    upper_bound_per_ha: Optional[float] = Field(None, description="Limite superior do intervalo de incerteza, por hectare.")
    uncertainty_method: Optional[str] = Field(None, description="Método usado para derivar o intervalo.")

    conversion_factors: Dict[str, float] = Field(default_factory=dict, description="Todos os fatores aplicados, nomeados.")
    model_version: str = Field(..., description="Versão do modelo/pipeline que produziu a estimativa.")
    quality_flags: List[str] = Field(default_factory=list, description="Sinalizadores de qualidade acumulados.")
    limitations: List[str] = Field(default_factory=list, description="Limitações que devem acompanhar o número.")

    @model_validator(mode="after")
    def _validate_coherence(self) -> "BiomassEstimate":
        """Garante que unidade, suporte temporal, período e intervalo sejam coerentes com a métrica."""
        expected_per_ha, expected_total = METRIC_UNITS[self.metric_type]
        if self.unit_per_ha != expected_per_ha:
            raise ValueError(
                f"unit_per_ha '{self.unit_per_ha}' incompatível com metric_type "
                f"'{self.metric_type}' (esperado '{expected_per_ha}')."
            )
        if self.total_unit != expected_total:
            raise ValueError(
                f"total_unit '{self.total_unit}' incompatível com metric_type "
                f"'{self.metric_type}' (esperado '{expected_total}')."
            )

        expected_support = METRIC_TEMPORAL_SUPPORT[self.metric_type]
        if self.temporal_support != expected_support:
            raise ValueError(
                f"temporal_support '{self.temporal_support}' incompatível com metric_type "
                f"'{self.metric_type}' (esperado '{expected_support}')."
            )

        if self.period_end < self.period_start:
            raise ValueError("period_end não pode ser anterior a period_start.")

        if self.valid_observation_fraction is not None and not 0.0 <= self.valid_observation_fraction <= 1.0:
            raise ValueError("valid_observation_fraction deve estar entre 0 e 1.")

        bounds = (self.lower_bound_per_ha, self.upper_bound_per_ha)
        if all(bound is not None for bound in bounds) and bounds[0] > bounds[1]:
            raise ValueError("lower_bound_per_ha não pode ser maior que upper_bound_per_ha.")

        if self.uncertainty_method is None and any(bound is not None for bound in bounds):
            raise ValueError("Intervalo de incerteza informado sem uncertainty_method.")

        return self

    @property
    def is_productivity(self) -> bool:
        """Se a métrica é um fluxo de produção (não um estoque)."""
        return self.metric_type in (
            "monthly_dry_matter_productivity",
            "annual_dry_matter_productivity",
        )

    @property
    def is_annual(self) -> bool:
        """Se a métrica tem suporte anual (única base compatível com UA/ano)."""
        return self.temporal_support == "annual"

    @property
    def period_days(self) -> int:
        """Número de dias cobertos pelo período (fim exclusivo)."""
        return (self.period_end - self.period_start).days

    @property
    def metric_label(self) -> str:
        """Rótulo em PT-BR da métrica."""
        return METRIC_LABELS[self.metric_type]

    @property
    def unit_label(self) -> str:
        """Unidade por hectare em PT-BR."""
        return UNIT_LABELS.get(self.unit_per_ha, self.unit_per_ha)

    def period_label(self) -> str:
        """Período formatado como dd/mm/aaaa a dd/mm/aaaa (fim inclusivo para leitura humana)."""
        from datetime import timedelta

        last_day = self.period_end - timedelta(days=1)
        return f"{self.period_start.strftime('%d/%m/%Y')} a {last_day.strftime('%d/%m/%Y')}"

    def to_report_block(self) -> str:
        """
        Bloco de metadados obrigatório em todo mapa, gráfico e boletim.

        Returns:
            str: Bloco com Métrica, Fonte, Período, Unidade, Resolução do raster,
            Resolução efetiva da máscara, Cobertura válida, Incerteza, Versão e Limitações.
        """
        value = "indisponível" if self.value_per_ha is None else f"{self.value_per_ha:.2f} {self.unit_label}"

        source = self.source if not self.source_version else f"{self.source} ({self.source_version})"

        mask = self.pasture_mask_source
        if self.effective_mask_resolution_m is not None:
            mask += f", {self.effective_mask_resolution_m:g} m"
        if self.pasture_mask_reference_year is not None:
            mask += f", referência {self.pasture_mask_reference_year}"

        coverage = (
            "não informada" if self.valid_observation_fraction is None
            else f"{self.valid_observation_fraction * 100:.0f}%"
        )

        if self.lower_bound_per_ha is None or self.upper_bound_per_ha is None:
            uncertainty = "não quantificada"
        else:
            uncertainty = (
                f"{self.lower_bound_per_ha:.2f} a {self.upper_bound_per_ha:.2f} {self.unit_label}"
                f" ({self.uncertainty_method})"
            )

        lines = [
            f"Métrica: {self.metric_label}",
            f"Valor: {value}",
            f"Fonte: {source}",
            f"Período: {self.period_label()}",
            f"Unidade: {self.unit_label}",
            f"Resolução do raster: {self.raster_resolution_m:g} m",
            f"Resolução efetiva da máscara: {mask}",
            f"Cobertura válida: {coverage}",
            f"Incerteza: {uncertainty}",
            f"Versão: {self.model_version}",
        ]

        if self.total_value is not None:
            lines.insert(2, f"Total na área válida: {self.total_value:.2f} {UNIT_LABELS.get(self.total_unit, self.total_unit)}")

        if self.limitations:
            lines.append("Limitações: " + " ".join(self.limitations))
        if self.quality_flags:
            lines.append("Sinalizadores: " + ", ".join(self.quality_flags))

        return "\n".join(lines)

    def __str__(self) -> str:
        return self.to_report_block()


class ForageParameters(BaseModel):
    """
    Parâmetros de manejo usados para converter biomassa em pé em forragem disponível.

    Nenhum deles tem valor universal: todos são configuráveis por sistema de manejo,
    espécie forrageira, estação e objetivo produtivo, e todos são devolvidos junto
    com o resultado para que a conta fique auditável.
    """
    residual_dm_t_ha: float = Field(..., ge=0.0, description="Resíduo mínimo pós-pastejo, em t MS/ha.")
    utilization_rate: float = Field(..., gt=0.0, le=1.0, description="Taxa de utilização da forragem acima do resíduo (0-1).")

    management_system: str = Field(..., description="Sistema de manejo (contínuo, rotacionado, diferido...).")
    forage_species: Optional[str] = Field(None, description="Espécie/cultivar forrageira predominante.")
    season: Optional[str] = Field(None, description="Estação considerada (águas, seca, transição).")
    rest_period_days: Optional[int] = Field(None, gt=0, description="Intervalo de descanso adotado, em dias.")
    animal_category: Optional[str] = Field(None, description="Categoria animal (cria, recria, engorda...).")
    supplementation: Optional[str] = Field(None, description="Suplementação praticada, quando houver.")
    current_stocking_ua_ha: Optional[float] = Field(None, ge=0.0, description="Lotação atual informada, em UA/ha.")
    excluded_area_ha: float = Field(0.0, ge=0.0, description="Área excluída (degradada, em recuperação, APP...), em ha.")

    source: str = Field(..., description="Referência técnica dos parâmetros adotados.")

    def __str__(self) -> str:
        lines = [
            f"- Sistema de manejo: {self.management_system}",
            f"- Resíduo mínimo: {self.residual_dm_t_ha:.2f} t MS/ha",
            f"- Taxa de utilização: {self.utilization_rate * 100:.0f}%",
        ]
        if self.forage_species:
            lines.append(f"- Espécie forrageira: {self.forage_species}")
        if self.season:
            lines.append(f"- Estação: {self.season}")
        if self.rest_period_days:
            lines.append(f"- Intervalo de descanso: {self.rest_period_days} dias")
        if self.animal_category:
            lines.append(f"- Categoria animal: {self.animal_category}")
        if self.supplementation:
            lines.append(f"- Suplementação: {self.supplementation}")
        if self.current_stocking_ua_ha is not None:
            lines.append(f"- Lotação atual informada: {self.current_stocking_ua_ha:.2f} UA/ha")
        if self.excluded_area_ha:
            lines.append(f"- Área excluída do cálculo: {self.excluded_area_ha:.2f} ha")
        lines.append(f"- Fonte dos parâmetros: {self.source}")
        return "\n".join(lines)


class StockingCapacityEstimate(BaseModel):
    """
    Capacidade de suporte, sempre separada em quatro grandezas distintas.

    `capacidade_anual_potencial` só existe sobre produtividade anual (ou sobre uma
    série mensal anualizada); `capacidade_no_periodo` é a oferta do período a partir
    de forragem disponível; `lotacao_atual_informada` vem do produtor; e
    `saldo_forrageiro_estimado` é a diferença entre oferta e demanda.
    """
    basis_metric_type: MetricType = Field(..., description="Métrica que serviu de base para o cálculo.")
    basis_period_start: date = Field(..., description="Início do período da métrica base.")
    basis_period_end: date = Field(..., description="Fim do período da métrica base (exclusivo).")
    basis_temporal_support: TemporalSupport = Field(..., description="Suporte temporal da métrica base.")

    pasture_area_ha: float = Field(..., gt=0.0, description="Área de pastagem considerada, em hectares.")

    annual_potential_capacity_ua: Optional[float] = Field(None, description="Capacidade anual potencial, em UA totais.")
    annual_potential_capacity_ua_ha: Optional[float] = Field(None, description="Capacidade anual potencial, em UA/ha.")

    period_capacity_ua: Optional[float] = Field(None, description="Capacidade no período, em UA totais.")
    period_capacity_ua_ha: Optional[float] = Field(None, description="Capacidade no período, em UA/ha.")
    period_days: Optional[int] = Field(None, gt=0, description="Duração do período de oferta, em dias.")

    reported_stocking_ua: Optional[float] = Field(None, description="Lotação atual informada, em UA totais.")
    reported_stocking_ua_ha: Optional[float] = Field(None, description="Lotação atual informada, em UA/ha.")

    forage_balance_t_dm: Optional[float] = Field(None, description="Saldo forrageiro estimado, em t MS.")

    ua_live_weight_kg: float = Field(..., description="Peso vivo de referência de 1 UA, em kg.")
    daily_intake_rate: float = Field(..., description="Consumo diário como fração do peso vivo.")
    trampling_loss_factor: float = Field(..., description="Fator de perda por pisoteio aplicado à demanda.")
    annual_demand_t_dm_per_ua: float = Field(..., description="Demanda anual por UA, em t MS/UA/ano.")

    model_version: str = Field(..., description="Versão do pipeline de capacidade de suporte.")
    quality_flags: List[str] = Field(default_factory=list, description="Sinalizadores herdados e próprios.")
    limitations: List[str] = Field(default_factory=list, description="Limitações que devem acompanhar o número.")

    def __str__(self) -> str:
        lines = ["Capacidade de suporte estimada"]
        lines.append(f"- Base: {METRIC_LABELS[self.basis_metric_type]} ({self.basis_temporal_support})")
        lines.append(
            f"- Período da base: {self.basis_period_start.strftime('%d/%m/%Y')} a "
            f"{self.basis_period_end.strftime('%d/%m/%Y')}"
        )
        lines.append(f"- Área de pastagem considerada: {self.pasture_area_ha:.2f} ha")

        if self.annual_potential_capacity_ua is not None:
            lines.append(
                f"- Capacidade anual potencial: {self.annual_potential_capacity_ua:.2f} UA "
                f"({self.annual_potential_capacity_ua_ha:.2f} UA/ha)"
            )
        if self.period_capacity_ua is not None:
            lines.append(
                f"- Capacidade no período ({self.period_days} dias): {self.period_capacity_ua:.2f} UA "
                f"({self.period_capacity_ua_ha:.2f} UA/ha)"
            )
        if self.reported_stocking_ua is not None:
            lines.append(
                f"- Lotação atual informada: {self.reported_stocking_ua:.2f} UA "
                f"({self.reported_stocking_ua_ha:.2f} UA/ha)"
            )
        if self.forage_balance_t_dm is not None:
            lines.append(f"- Saldo forrageiro estimado: {self.forage_balance_t_dm:.2f} t MS")

        lines.append(
            f"- Demanda adotada: {self.annual_demand_t_dm_per_ua:.2f} t MS/UA/ano "
            f"(1 UA = {self.ua_live_weight_kg:.0f} kg, consumo {self.daily_intake_rate * 100:.1f}% PV/dia, "
            f"fator de perda por pisoteio {self.trampling_loss_factor:g}x)"
        )
        lines.append(f"- Versão: {self.model_version}")

        if self.limitations:
            lines.append("- Limitações: " + " ".join(self.limitations))
        if self.quality_flags:
            lines.append("- Sinalizadores: " + ", ".join(self.quality_flags))

        return "\n".join(lines)
