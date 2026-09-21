"""Forragem disponível para pastejo (t MS/ha).

Só existe depois que há biomassa EM PÉ estimada:

    forragem_disponível = max(biomassa_em_pé - resíduo_mínimo, 0) x taxa_de_utilização

O resíduo mínimo é a massa que precisa ficar no piquete para a rebrota; a taxa de
utilização é a fração do excedente que o animal de fato colhe. Nenhum dos dois tem
valor universal — variam com sistema de manejo, espécie forrageira, estação e
objetivo produtivo — e por isso os parâmetros adotados sempre acompanham o
resultado.
"""

from typing import Dict, List, Optional

from app.schemas.biomass_schemas import BiomassEstimate, ForageParameters
from app.services.geospatial.biomass.biomass_validation import (
    ValidationReport,
    assert_is_stock_metric,
    assert_within_envelope,
)


FORAGE_MODEL_VERSION = "available-forage-v1"

_DEFAULT_SOURCE = (
    "Embrapa Gado de Corte - manejo do pastejo de Urochloa spp.; "
    "Da Silva & Nascimento Jr. (2007) - metas de altura e resíduo pós-pastejo"
)

# Parâmetros padrão por sistema de manejo. São PADRÕES, não verdades: qualquer
# um deles pode ser sobrescrito, e o valor efetivamente usado vai no resultado.
#
#   * contínuo    - resíduo mais alto e utilização baixa, porque o animal
#                   seleciona e o rebaixamento é desigual;
#   * rotacionado - resíduo definido pela meta de altura pós-pastejo e utilização
#                   maior, com o piquete ocupado por poucos dias;
#   * diferido    - massa acumulada na seca, utilização alta e resíduo menor,
#                   assumindo que a área será recuperada nas águas.
MANAGEMENT_DEFAULTS: Dict[str, Dict[str, float]] = {
    "continuo": {"residual_dm_t_ha": 2.0, "utilization_rate": 0.40},
    "rotacionado": {"residual_dm_t_ha": 1.5, "utilization_rate": 0.55},
    "diferido": {"residual_dm_t_ha": 1.0, "utilization_rate": 0.65},
}

# Ajuste sazonal da taxa de utilização. Na seca o rebrote é lento e a pressão de
# pastejo precisa ser menor para não comprometer a rebrota das águas.
SEASONAL_UTILIZATION_ADJUSTMENT: Dict[str, float] = {
    "aguas": 1.0,
    "transicao": 0.85,
    "seca": 0.70,
}


def default_parameters(
    management_system: str = "continuo",
    season: Optional[str] = None,
    forage_species: Optional[str] = None,
    **overrides,
) -> ForageParameters:
    """
    Parâmetros padrão de manejo, ajustados pela estação e sobrescritos sob demanda.

    Args:
        management_system (str): "continuo", "rotacionado" ou "diferido".
        season (str, optional): "aguas", "transicao" ou "seca".
        forage_species (str, optional): Espécie/cultivar predominante.
        **overrides: Qualquer campo de `ForageParameters` a sobrescrever.

    Returns:
        ForageParameters: Parâmetros com a fonte técnica registrada.

    Raises:
        ValueError: Se o sistema de manejo ou a estação não forem reconhecidos.
    """
    if management_system not in MANAGEMENT_DEFAULTS:
        raise ValueError(
            f"Sistema de manejo '{management_system}' desconhecido. "
            f"Disponíveis: {', '.join(MANAGEMENT_DEFAULTS)}."
        )

    defaults = dict(MANAGEMENT_DEFAULTS[management_system])

    if season is not None:
        if season not in SEASONAL_UTILIZATION_ADJUSTMENT:
            raise ValueError(
                f"Estação '{season}' desconhecida. "
                f"Disponíveis: {', '.join(SEASONAL_UTILIZATION_ADJUSTMENT)}."
            )
        defaults["utilization_rate"] *= SEASONAL_UTILIZATION_ADJUSTMENT[season]

    payload = {
        "management_system": management_system,
        "season": season,
        "forage_species": forage_species,
        "source": _DEFAULT_SOURCE,
        **defaults,
    }
    payload.update(overrides)

    return ForageParameters(**payload)


def compute_available_forage_t_ha(
    standing_dm_t_ha: float,
    residual_dm_t_ha: float,
    utilization_rate: float,
) -> float:
    """
    A conta de forragem disponível, isolada para poder ser testada sozinha.

    Args:
        standing_dm_t_ha (float): Biomassa em pé, em t MS/ha.
        residual_dm_t_ha (float): Resíduo mínimo pós-pastejo, em t MS/ha.
        utilization_rate (float): Taxa de utilização do excedente (0-1).

    Returns:
        float: Forragem disponível, em t MS/ha (nunca negativa).
    """
    return max(standing_dm_t_ha - residual_dm_t_ha, 0.0) * utilization_rate


def estimate_available_forage(
    standing: BiomassEstimate,
    parameters: Optional[ForageParameters] = None,
) -> BiomassEstimate:
    """
    Converte biomassa em pé em forragem disponível para pastejo.

    Args:
        standing (BiomassEstimate): Estimativa de `standing_dry_matter_biomass`.
        parameters (ForageParameters, optional): Parâmetros de manejo; None usa o
            padrão de pastejo contínuo.

    Returns:
        BiomassEstimate: Estimativa de `available_forage`, carregando os parâmetros
        usados dentro de `conversion_factors` e nas limitações.

    Raises:
        IncompatibleTemporalSupportError: Se a entrada for produtividade (fluxo).
        ValueError: Se a entrada não tiver valor estimado.
        ImplausibleEstimateError: Se o resultado estourar o envelope agronômico.
    """
    assert_is_stock_metric(standing.metric_type)

    if standing.metric_type != "standing_dry_matter_biomass":
        raise ValueError(
            f"Forragem disponível exige 'standing_dry_matter_biomass'; recebido "
            f"'{standing.metric_type}'."
        )

    if standing.value_per_ha is None:
        raise ValueError(
            "A estimativa de biomassa em pé não tem valor; não há forragem a calcular."
        )

    params = parameters or default_parameters()

    value_per_ha = compute_available_forage_t_ha(
        standing_dm_t_ha=standing.value_per_ha,
        residual_dm_t_ha=params.residual_dm_t_ha,
        utilization_rate=params.utilization_rate,
    )

    bounds: List[Optional[float]] = []
    for bound in (standing.lower_bound_per_ha, standing.upper_bound_per_ha):
        bounds.append(
            None if bound is None
            else compute_available_forage_t_ha(bound, params.residual_dm_t_ha, params.utilization_rate)
        )

    effective_area_ha = None
    if standing.valid_area_ha is not None:
        effective_area_ha = max(standing.valid_area_ha - params.excluded_area_ha, 0.0)

    report = ValidationReport()
    report.merge(standing.quality_flags)
    report.merge(assert_within_envelope("available_forage", value_per_ha))

    if value_per_ha == 0.0:
        report.merge(["below_residual_threshold"])

    limitations = [
        f"Resíduo mínimo de {params.residual_dm_t_ha:.2f} t MS/ha e taxa de utilização de "
        f"{params.utilization_rate * 100:.0f}% ({params.management_system}"
        + (f", {params.season}" if params.season else "")
        + f"). Fonte: {params.source}.",
    ]
    if params.excluded_area_ha:
        limitations.append(
            f"{params.excluded_area_ha:.2f} ha excluídos do cálculo (área degradada, "
            "em recuperação ou não pastejável)."
        )
    limitations.append(
        "Oferta instantânea de forragem; não é produção acumulada nem capacidade de "
        "suporte anual."
    )

    return BiomassEstimate(
        metric_type="available_forage",
        source=standing.source,
        source_version=standing.source_version,
        period_start=standing.period_start,
        period_end=standing.period_end,
        temporal_support="instantaneous",
        value_per_ha=value_per_ha,
        total_value=None if effective_area_ha is None else value_per_ha * effective_area_ha,
        unit_per_ha="t_DM_ha",
        total_unit="t_DM",
        raster_resolution_m=standing.raster_resolution_m,
        effective_mask_resolution_m=standing.effective_mask_resolution_m,
        pasture_mask_source=standing.pasture_mask_source,
        pasture_mask_reference_year=standing.pasture_mask_reference_year,
        pasture_mask=standing.pasture_mask,
        valid_area_ha=effective_area_ha,
        valid_observation_fraction=standing.valid_observation_fraction,
        lower_bound_per_ha=bounds[0],
        upper_bound_per_ha=bounds[1],
        uncertainty_method=(
            None if bounds[0] is None and bounds[1] is None
            else f"propagado de {standing.uncertainty_method}"
        ),
        conversion_factors={
            "residual_dm_t_ha": params.residual_dm_t_ha,
            "utilization_rate": params.utilization_rate,
            "excluded_area_ha": params.excluded_area_ha,
        },
        model_version=f"{FORAGE_MODEL_VERSION}({standing.model_version})",
        quality_flags=report.quality_flags,
        limitations=limitations,
    )
