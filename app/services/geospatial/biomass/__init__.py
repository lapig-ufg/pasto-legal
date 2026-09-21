"""Arquitetura de biomassa on-the-fly para pastagens.

Quatro métricas distintas, quatro módulos distintos:

    biomass_productivity  -> produtividade mensal (t MS/ha/mês) e anual (t MS/ha/ano)
    historical_biomass    -> série histórica anual 2000-2024 on-the-fly (+ export zarr/S3)
    standing_biomass      -> biomassa em pé (t MS/ha), modelo calibrado em campo
    available_forage      -> forragem disponível (t MS/ha)
    stocking_capacity     -> capacidade de suporte (UA/ha e UA totais)

mais os módulos de apoio:

    biomass_validation    -> contratos de unidade dos assets, envelopes e guardas
    pasture_mask          -> máscara de pastagem com metadados explícitos
    biomass_reporting     -> legendas, blocos de boletim e texto de chat
"""

from app.services.geospatial.biomass.biomass_assessment import (
    BiomassAssessment,
    assess_property_biomass,
)
from app.services.geospatial.biomass.available_forage import (
    compute_available_forage_t_ha,
    default_parameters,
    estimate_available_forage,
)
from app.services.geospatial.biomass.biomass_productivity import (
    annualize_monthly_series,
    available_annual_years,
    estimate_annual_productivity,
    estimate_monthly_productivity,
    latest_monthly_productivity,
)
from app.services.geospatial.biomass.biomass_reporting import (
    annotate_map,
    map_caption,
    metadata_rows,
    summarize_for_chat,
)
from app.services.geospatial.biomass.biomass_validation import (
    BiomassValidationError,
    ImplausibleEstimateError,
    IncompatibleTemporalSupportError,
    NoDataForPeriodError,
    UnverifiedUnitContractError,
    build_cache_key,
    get_contract,
)
from app.services.geospatial.biomass.historical_biomass import (
    estimate_historical_productivity,
    export_historical_series,
    gpp_to_dry_matter_t_ha,
    historical_series,
)
from app.services.geospatial.biomass.pasture_mask import build_pasture_mask
from app.services.geospatial.biomass.standing_biomass import (
    CalibratedModelUnavailableError,
    estimate_standing_biomass,
    train_standing_biomass_model,
)
from app.services.geospatial.biomass.stocking_capacity import (
    annual_demand_t_dm_per_ua,
    estimate_annual_potential_capacity,
    estimate_period_capacity,
)


__all__ = [
    "annotate_map",
    "assess_property_biomass",
    "BiomassAssessment",
    "annual_demand_t_dm_per_ua",
    "annualize_monthly_series",
    "available_annual_years",
    "build_cache_key",
    "build_pasture_mask",
    "BiomassValidationError",
    "CalibratedModelUnavailableError",
    "compute_available_forage_t_ha",
    "default_parameters",
    "estimate_annual_potential_capacity",
    "estimate_historical_productivity",
    "export_historical_series",
    "gpp_to_dry_matter_t_ha",
    "historical_series",
    "estimate_annual_productivity",
    "estimate_available_forage",
    "estimate_monthly_productivity",
    "estimate_period_capacity",
    "estimate_standing_biomass",
    "get_contract",
    "ImplausibleEstimateError",
    "IncompatibleTemporalSupportError",
    "latest_monthly_productivity",
    "map_caption",
    "metadata_rows",
    "NoDataForPeriodError",
    "summarize_for_chat",
    "train_standing_biomass_model",
    "UnverifiedUnitContractError",
]
