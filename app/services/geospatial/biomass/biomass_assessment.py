"""Orquestração: monta o conjunto de métricas de uma propriedade de uma vez.

É o ponto de entrada usado pelas ferramentas e pelo boletim. Cada métrica é
calculada pelo seu próprio módulo e falha de forma isolada: a ausência de
biomassa em pé (modelo ainda não calibrado) não impede a entrega da
produtividade mensal, e a ausência de produtividade mensal (fora da cobertura)
não faz a produtividade anual ser apresentada no lugar dela.
"""

import datetime

from dataclasses import dataclass, field
from typing import List, Optional

import ee

from agno.utils.log import log_info, log_warning

from app.schemas.biomass_schemas import (
    BiomassEstimate,
    ForageParameters,
    StockingCapacityEstimate,
)
from app.services.geospatial.biomass.available_forage import estimate_available_forage
from app.services.geospatial.biomass.biomass_productivity import (
    estimate_annual_productivity,
    latest_monthly_productivity,
)
from app.services.geospatial.biomass.biomass_reporting import summarize_for_chat
from app.services.geospatial.biomass.biomass_validation import BiomassValidationError
from app.services.geospatial.biomass.pasture_mask import PastureMask, build_pasture_mask
from app.services.geospatial.biomass.standing_biomass import (
    CalibratedModelUnavailableError,
    estimate_standing_biomass,
)
from app.services.geospatial.biomass.stocking_capacity import (
    estimate_annual_potential_capacity,
    estimate_period_capacity,
)


@dataclass
class BiomassAssessment:
    """
    Conjunto de métricas de uma propriedade, cada uma podendo estar ausente.

    Attributes:
        mask (PastureMask): Máscara de pastagem usada em todas as métricas.
        monthly_productivity (BiomassEstimate | None): t MS/ha/mês.
        annual_productivity (BiomassEstimate | None): t MS/ha/ano.
        standing_biomass (BiomassEstimate | None): t MS/ha em pé.
        available_forage (BiomassEstimate | None): t MS/ha pastejável.
        stocking_capacity (StockingCapacityEstimate | None): UA e UA/ha.
        unavailable (List[str]): Métricas ausentes e o motivo, em PT-BR.
    """
    mask: PastureMask
    monthly_productivity: Optional[BiomassEstimate] = None
    annual_productivity: Optional[BiomassEstimate] = None
    standing_biomass: Optional[BiomassEstimate] = None
    available_forage: Optional[BiomassEstimate] = None
    stocking_capacity: Optional[StockingCapacityEstimate] = None
    unavailable: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        text = summarize_for_chat(
            monthly=self.monthly_productivity,
            annual=self.annual_productivity,
            standing=self.standing_biomass,
            forage=self.available_forage,
            capacity=self.stocking_capacity,
        )

        if self.unavailable:
            text += "\n\n## Métricas indisponíveis\n" + "\n".join(
                f"- {item}" for item in self.unavailable
            )

        return text


def assess_property_biomass(
    roi: ee.Geometry,
    today: Optional[datetime.date] = None,
    mask_strategy: str = "official",
    forage_parameters: Optional[ForageParameters] = None,
    reported_stocking_ua: Optional[float] = None,
    grazing_days: Optional[int] = None,
) -> BiomassAssessment:
    """
    Calcula todas as métricas disponíveis para a propriedade.

    A capacidade de suporte é liberada pela via compatível com o dado existente:
    anual sobre produtividade anual, ou por período sobre forragem disponível
    quando `grazing_days` é informado. Nunca sobre produtividade mensal.

    Args:
        roi (ee.Geometry): Região de interesse (polígono do imóvel).
        today (datetime.date, optional): Data de referência; None usa hoje.
        mask_strategy (str): "official", "on_the_fly" ou "hybrid".
        forage_parameters (ForageParameters, optional): Manejo para a forragem disponível.
        reported_stocking_ua (float, optional): Lotação atual informada, em UA totais.
        grazing_days (int, optional): Horizonte de pastejo para a capacidade no período.

    Returns:
        BiomassAssessment: Métricas disponíveis e a lista do que faltou, com o motivo.
    """
    reference = today or datetime.date.today()
    mask = build_pasture_mask(roi=roi, strategy=mask_strategy)

    assessment = BiomassAssessment(mask=mask)

    assessment.monthly_productivity = latest_monthly_productivity(
        roi=roi, mask=mask, today=reference
    )
    if assessment.monthly_productivity is None:
        assessment.unavailable.append(
            "Produtividade mensal: a série Time2Graze não cobre esta propriedade ou "
            "este período. A produtividade anual do MapBiomas NÃO a substitui — é "
            "outra métrica, com outro período e outra unidade."
        )

    try:
        assessment.annual_productivity = estimate_annual_productivity(roi=roi)
    except (ValueError, BiomassValidationError) as error:
        log_warning(f"assess_property_biomass: produtividade anual indisponível: {error}")
        assessment.unavailable.append(f"Produtividade anual: {error}")

    try:
        assessment.standing_biomass = estimate_standing_biomass(
            roi=roi, target_date=reference, mask=mask
        )
    except CalibratedModelUnavailableError as error:
        log_info(f"assess_property_biomass: biomassa em pé indisponível: {error}")
        assessment.unavailable.append(f"Biomassa em pé: {error}")
    except (ImportError, BiomassValidationError) as error:
        log_warning(f"assess_property_biomass: biomassa em pé falhou: {error}")
        assessment.unavailable.append(f"Biomassa em pé: {error}")

    if assessment.standing_biomass is not None:
        try:
            assessment.available_forage = estimate_available_forage(
                assessment.standing_biomass, parameters=forage_parameters
            )
        except (ValueError, BiomassValidationError) as error:
            log_warning(f"assess_property_biomass: forragem disponível falhou: {error}")
            assessment.unavailable.append(f"Forragem disponível: {error}")
    else:
        assessment.unavailable.append(
            "Forragem disponível: depende da biomassa em pé, que não está disponível."
        )

    assessment.stocking_capacity = _capacity(
        assessment=assessment,
        reported_stocking_ua=reported_stocking_ua,
        forage_parameters=forage_parameters,
        grazing_days=grazing_days,
    )

    return assessment


def _capacity(
    assessment: BiomassAssessment,
    reported_stocking_ua: Optional[float],
    forage_parameters: Optional[ForageParameters],
    grazing_days: Optional[int],
) -> Optional[StockingCapacityEstimate]:
    """
    Escolhe a via de capacidade de suporte compatível com o dado disponível.

    Prioriza a capacidade no período quando há forragem disponível e horizonte de
    pastejo informado (é a estimativa mais próxima da condição atual); caso
    contrário usa a produtividade anual. Produtividade mensal nunca é usada.

    Args:
        assessment (BiomassAssessment): Métricas já calculadas.
        reported_stocking_ua (float, optional): Lotação atual informada, em UA totais.
        forage_parameters (ForageParameters, optional): Parâmetros de manejo.
        grazing_days (int, optional): Horizonte de pastejo, em dias.

    Returns:
        StockingCapacityEstimate | None: Capacidade calculada, ou None.
    """
    if assessment.available_forage is not None and grazing_days:
        try:
            return estimate_period_capacity(
                assessment.available_forage,
                grazing_days=grazing_days,
                parameters=forage_parameters,
                reported_stocking_ua=reported_stocking_ua,
            )
        except (ValueError, BiomassValidationError) as error:
            log_warning(f"_capacity: capacidade no período falhou: {error}")

    if assessment.annual_productivity is not None:
        try:
            return estimate_annual_potential_capacity(
                assessment.annual_productivity,
                pasture_area_ha=assessment.mask.metadata.pasture_area_ha,
                reported_stocking_ua=reported_stocking_ua,
            )
        except (ValueError, BiomassValidationError) as error:
            log_warning(f"_capacity: capacidade anual falhou: {error}")

    assessment.unavailable.append(
        "Capacidade de suporte: exige produtividade anual (ou 12 meses acumulados), "
        "ou forragem disponível com horizonte de pastejo informado. A produtividade "
        "mensal sozinha não é base válida para UA/ano."
    )
    return None
