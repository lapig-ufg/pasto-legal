"""Capacidade de suporte (UA/ha e UA totais), liberada só sobre métrica compatível.

A demanda animal é expressa em t MS por UA por ANO. Dividir uma produtividade
mensal por esse denominador subestima a capacidade em cerca de 12x. Por isso o
cálculo em base anual é liberado apenas quando:

  * a estimativa tem suporte temporal anual (MapBiomas, ou série mensal anualizada
    por `annualize_monthly_series`); ou
  * o usuário fornece manejo e o cálculo é feito por período, a partir de forragem
    disponível — e aí o resultado é `capacidade_no_período`, nunca anual.

As quatro grandezas ficam separadas no resultado:

    capacidade_anual_potencial   - o que a produtividade do ano sustenta
    capacidade_no_periodo        - o que a forragem disponível sustenta no período
    lotacao_atual_informada      - o que o produtor declarou
    saldo_forrageiro_estimado    - oferta menos demanda
"""

from typing import Optional

from app.schemas.biomass_schemas import (
    BiomassEstimate,
    ForageParameters,
    StockingCapacityEstimate,
)
from app.services.geospatial.biomass.biomass_validation import (
    ValidationReport,
    assert_annualizable,
)


STOCKING_MODEL_VERSION = "stocking-capacity-v1"

# 1 UA = 450 kg de peso vivo (padrão Nelore adotado pela Metodologia LAPIG).
UA_LIVE_WEIGHT_KG = 450.0

# Consumo diário de matéria seca: 2,5% do peso vivo.
DAILY_INTAKE_RATE = 0.025

# Fator de perda por pisoteio: assume-se que metade da matéria seca ofertada é
# perdida por pisoteio, fezes e senescência, então a demanda é dobrada. É a
# margem de proteção da Metodologia LAPIG.
TRAMPLING_LOSS_FACTOR = 2.0

DEMAND_SOURCE = (
    "Metodologia LAPIG: 1 UA = 450 kg PV (Nelore), consumo de 2,5% PV/dia em "
    "matéria seca, com fator 2x de perda por pisoteio"
)


def daily_demand_t_dm_per_ua(
    ua_live_weight_kg: float = UA_LIVE_WEIGHT_KG,
    daily_intake_rate: float = DAILY_INTAKE_RATE,
    trampling_loss_factor: float = TRAMPLING_LOSS_FACTOR,
) -> float:
    """
    Demanda diária de matéria seca por UA, em t MS/UA/dia.

    Args:
        ua_live_weight_kg (float): Peso vivo de referência de 1 UA, em kg.
        daily_intake_rate (float): Consumo diário como fração do peso vivo.
        trampling_loss_factor (float): Multiplicador de perda por pisoteio.

    Returns:
        float: Demanda diária, em t MS/UA/dia.
    """
    return ua_live_weight_kg * daily_intake_rate * trampling_loss_factor / 1000.0


def annual_demand_t_dm_per_ua(
    ua_live_weight_kg: float = UA_LIVE_WEIGHT_KG,
    daily_intake_rate: float = DAILY_INTAKE_RATE,
    trampling_loss_factor: float = TRAMPLING_LOSS_FACTOR,
    days_per_year: int = 365,
) -> float:
    """
    Demanda anual de matéria seca por UA, em t MS/UA/ano.

    Com os parâmetros padrão o resultado é 8,21 t MS/UA/ano — o divisor 8,2 da
    Metodologia LAPIG, aqui derivado dos seus componentes em vez de escrito como
    constante mágica.

    Args:
        ua_live_weight_kg (float): Peso vivo de referência de 1 UA, em kg.
        daily_intake_rate (float): Consumo diário como fração do peso vivo.
        trampling_loss_factor (float): Multiplicador de perda por pisoteio.
        days_per_year (int): Dias considerados no ano.

    Returns:
        float: Demanda anual, em t MS/UA/ano.
    """
    return daily_demand_t_dm_per_ua(
        ua_live_weight_kg, daily_intake_rate, trampling_loss_factor
    ) * days_per_year


def estimate_annual_potential_capacity(
    estimate: BiomassEstimate,
    pasture_area_ha: Optional[float] = None,
    reported_stocking_ua: Optional[float] = None,
    ua_live_weight_kg: float = UA_LIVE_WEIGHT_KG,
    daily_intake_rate: float = DAILY_INTAKE_RATE,
    trampling_loss_factor: float = TRAMPLING_LOSS_FACTOR,
) -> StockingCapacityEstimate:
    """
    Capacidade anual potencial, em UA e UA/ha, a partir de produtividade ANUAL.

    Args:
        estimate (BiomassEstimate): Produtividade anual (MapBiomas ou série anualizada).
        pasture_area_ha (float, optional): Área de pastagem; None usa `valid_area_ha`.
        reported_stocking_ua (float, optional): Lotação atual informada, em UA totais.
        ua_live_weight_kg (float): Peso vivo de referência de 1 UA, em kg.
        daily_intake_rate (float): Consumo diário como fração do peso vivo.
        trampling_loss_factor (float): Multiplicador de perda por pisoteio.

    Returns:
        StockingCapacityEstimate: Capacidade anual potencial, lotação informada e saldo.

    Raises:
        IncompatibleTemporalSupportError: Se a métrica não for anual — inclusive
            quando for produtividade mensal.
        ValueError: Se não houver valor ou área de pastagem.
    """
    assert_annualizable(
        metric_type=estimate.metric_type,
        temporal_support=estimate.temporal_support,
        period_days=estimate.period_days,
    )

    if estimate.value_per_ha is None:
        raise ValueError("A estimativa base não tem valor; não há capacidade a calcular.")

    area_ha = pasture_area_ha if pasture_area_ha is not None else estimate.valid_area_ha
    if area_ha is None or area_ha <= 0:
        raise ValueError(
            "Área de pastagem desconhecida ou nula; a capacidade de suporte total "
            "não pode ser calculada."
        )

    demand = annual_demand_t_dm_per_ua(
        ua_live_weight_kg, daily_intake_rate, trampling_loss_factor
    )

    total_dm = estimate.value_per_ha * area_ha
    capacity_ua = total_dm / demand
    capacity_ua_ha = capacity_ua / area_ha

    balance = None
    reported_ua_ha = None
    if reported_stocking_ua is not None:
        reported_ua_ha = reported_stocking_ua / area_ha
        balance = total_dm - reported_stocking_ua * demand

    report = ValidationReport()
    report.merge(estimate.quality_flags)

    limitations = [
        "Capacidade anual POTENCIAL: o que a produtividade estimada do ano sustentaria "
        "em média, não a lotação recomendada para o mês atual.",
        f"Demanda adotada: {demand:.2f} t MS/UA/ano. {DEMAND_SOURCE}.",
    ]
    if "annualized_from_monthly_series" in estimate.quality_flags:
        limitations.append(
            "Base anualizada a partir de 12 estimativas mensais, não do produto anual "
            "consolidado."
        )
    limitations.extend(estimate.limitations)

    return StockingCapacityEstimate(
        basis_metric_type=estimate.metric_type,
        basis_period_start=estimate.period_start,
        basis_period_end=estimate.period_end,
        basis_temporal_support=estimate.temporal_support,
        pasture_area_ha=area_ha,
        annual_potential_capacity_ua=capacity_ua,
        annual_potential_capacity_ua_ha=capacity_ua_ha,
        reported_stocking_ua=reported_stocking_ua,
        reported_stocking_ua_ha=reported_ua_ha,
        forage_balance_t_dm=balance,
        ua_live_weight_kg=ua_live_weight_kg,
        daily_intake_rate=daily_intake_rate,
        trampling_loss_factor=trampling_loss_factor,
        annual_demand_t_dm_per_ua=demand,
        model_version=STOCKING_MODEL_VERSION,
        quality_flags=report.quality_flags,
        limitations=limitations,
    )


def estimate_period_capacity(
    forage: BiomassEstimate,
    grazing_days: int,
    pasture_area_ha: Optional[float] = None,
    parameters: Optional[ForageParameters] = None,
    reported_stocking_ua: Optional[float] = None,
    ua_live_weight_kg: float = UA_LIVE_WEIGHT_KG,
    daily_intake_rate: float = DAILY_INTAKE_RATE,
    trampling_loss_factor: float = TRAMPLING_LOSS_FACTOR,
) -> StockingCapacityEstimate:
    """
    Capacidade no período, a partir de forragem disponível e de um horizonte de pastejo.

    Esta é a via legítima quando não há base anual: a oferta instantânea de forragem
    sustenta N UA por `grazing_days` dias. O resultado NÃO é capacidade anual e não
    deve ser apresentado como tal.

    Args:
        forage (BiomassEstimate): Estimativa de `available_forage`.
        grazing_days (int): Horizonte de pastejo considerado, em dias.
        pasture_area_ha (float, optional): Área de pastagem; None usa `valid_area_ha`.
        parameters (ForageParameters, optional): Parâmetros de manejo, para a lotação informada.
        reported_stocking_ua (float, optional): Lotação atual informada, em UA totais.
        ua_live_weight_kg (float): Peso vivo de referência de 1 UA, em kg.
        daily_intake_rate (float): Consumo diário como fração do peso vivo.
        trampling_loss_factor (float): Multiplicador de perda por pisoteio.

    Returns:
        StockingCapacityEstimate: Capacidade no período, lotação informada e saldo.

    Raises:
        ValueError: Se a métrica não for forragem disponível, se `grazing_days` não
            for positivo, ou se faltarem valor e área.
    """
    if forage.metric_type != "available_forage":
        raise ValueError(
            f"A capacidade no período exige 'available_forage'; recebido "
            f"'{forage.metric_type}'. Produtividade mensal não é oferta de forragem."
        )

    if grazing_days <= 0:
        raise ValueError("O horizonte de pastejo deve ser de pelo menos 1 dia.")

    if forage.value_per_ha is None:
        raise ValueError("A estimativa de forragem não tem valor; não há capacidade a calcular.")

    area_ha = pasture_area_ha if pasture_area_ha is not None else forage.valid_area_ha
    if area_ha is None or area_ha <= 0:
        raise ValueError(
            "Área de pastagem desconhecida ou nula; a capacidade no período não pode "
            "ser calculada."
        )

    daily_demand = daily_demand_t_dm_per_ua(
        ua_live_weight_kg, daily_intake_rate, trampling_loss_factor
    )

    total_forage = forage.value_per_ha * area_ha
    capacity_ua = total_forage / (daily_demand * grazing_days)
    capacity_ua_ha = capacity_ua / area_ha

    reported_ua = reported_stocking_ua
    if reported_ua is None and parameters is not None and parameters.current_stocking_ua_ha is not None:
        reported_ua = parameters.current_stocking_ua_ha * area_ha

    balance = None
    reported_ua_ha = None
    if reported_ua is not None:
        reported_ua_ha = reported_ua / area_ha
        balance = total_forage - reported_ua * daily_demand * grazing_days

    report = ValidationReport()
    report.merge(forage.quality_flags)
    report.merge(["period_capacity_not_annual"])

    limitations = [
        f"Capacidade NO PERÍODO: a forragem disponível estimada sustenta essa lotação "
        f"por {grazing_days} dias. Não é capacidade anual e não pode ser extrapolada "
        "para o ano sem uma série de 12 meses.",
        f"Demanda adotada: {daily_demand * 1000:.1f} kg MS/UA/dia. {DEMAND_SOURCE}.",
    ]
    limitations.extend(forage.limitations)

    return StockingCapacityEstimate(
        basis_metric_type=forage.metric_type,
        basis_period_start=forage.period_start,
        basis_period_end=forage.period_end,
        basis_temporal_support=forage.temporal_support,
        pasture_area_ha=area_ha,
        period_capacity_ua=capacity_ua,
        period_capacity_ua_ha=capacity_ua_ha,
        period_days=grazing_days,
        reported_stocking_ua=reported_ua,
        reported_stocking_ua_ha=reported_ua_ha,
        forage_balance_t_dm=balance,
        ua_live_weight_kg=ua_live_weight_kg,
        daily_intake_rate=daily_intake_rate,
        trampling_loss_factor=trampling_loss_factor,
        annual_demand_t_dm_per_ua=annual_demand_t_dm_per_ua(
            ua_live_weight_kg, daily_intake_rate, trampling_loss_factor
        ),
        model_version=STOCKING_MODEL_VERSION,
        quality_flags=report.quality_flags,
        limitations=limitations,
    )
