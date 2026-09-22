"""Produtividade de matéria seca: mensal (Time2Graze/uGPP) e anual (MapBiomas).

As duas fontes respondem à mesma pergunta — quanto o pasto PRODUZIU — em janelas
temporais diferentes, e por isso são métricas diferentes:

    Time2Graze uGPP -> monthly_dry_matter_productivity  (t MS/ha/mês)
    MapBiomas       -> annual_dry_matter_productivity   (t MS/ha/ano)

Nenhuma das duas é biomassa em pé nem forragem disponível, e nenhuma pode
substituir a outra: quando não há dado mensal para o período, a função mensal
devolve `None` (ou levanta `NoDataForPeriodError`) em vez de servir o valor anual
do MapBiomas travestido de estimativa do mês.

A cadeia de fatores aplicada à fonte mensal é, por pixel:

    DN bruto
      x asset_scale          -> MJ/m²/dia de APAR
      x grass_lue            -> gC/m²/dia
      x carbon_to_dry_matter -> g MS/m²/dia
      x n_days               -> g MS/m² no período
      x unit_conversion      -> t MS/ha no período

Todos os fatores vêm de `biomass_validation` e são devolvidos dentro da
estimativa, em `conversion_factors`.
"""

import calendar
import datetime

from typing import Dict, List, Optional, Tuple

import ee

from agno.utils.log import log_warning

from app.schemas.biomass_schemas import BiomassEstimate
from app.services.geospatial.biomass.biomass_validation import (
    AssetUnitContract,
    CARBON_TO_DRY_MATTER,
    GRAMS_PER_M2_TO_TONS_PER_HA,
    GRASS_LUE_MAX_GC_PER_MJ,
    GRASS_LUE_MIN_GC_PER_MJ,
    GRASS_LUE_UPPER_GC_PER_MJ,
    MAPBIOMAS_PASTURE_BIOMASS_CONTRACT,
    NoDataForPeriodError,
    T2G_UGPP_CF_CONTRACT,
    T2G_UGPP_CONTRACTS,
    T2G_UGPP_PROD_CONTRACT,
    ValidationReport,
    assert_within_envelope,
    contract_quality_flags,
    observation_quality_flags,
)
from app.services.geospatial.biomass.pasture_mask import PastureMask, build_pasture_mask


MONTHLY_MODEL_VERSION = "monthly-productivity-v1"
ANNUAL_MODEL_VERSION = "annual-productivity-v1"

UNCERTAINTY_METHOD = "faixa de LUEmax da literatura (0,40-0,65 gC/MJ)"

# Meses em PT-BR para as legendas e para o texto entregue ao usuário.
MONTH_NAMES = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
    7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}

# Quantos meses para trás procurar quando o chamador pede "o mês mais recente".
_LATEST_MONTH_LOOKBACK = 18

# Dias mínimos de mês corrido para que valha a pena chamar o resultado de
# "produtividade do mês". Abaixo disso o acumulado é curto demais para ser
# comparável a um mês inteiro, e o correto é entregar o último mês completo.
MIN_OBSERVABLE_DAYS = 10


# -----------------------------------------------------------------------------
# Aritmética pura (sem Earth Engine) — é o que os testes de unidade exercitam
# -----------------------------------------------------------------------------

def monthly_period(
    year: int,
    month: int,
    today: Optional[datetime.date] = None,
) -> Tuple[datetime.date, datetime.date]:
    """
    Período de acumulação de um mês calendário, com fim exclusivo.

    Quando o mês pedido é o mês corrente, o fim é truncado em `today` — o período
    devolvido é o que de fato pode ser observado, e não o mês inteiro.

    Args:
        year (int): Ano do mês pedido.
        month (int): Mês pedido (1-12).
        today (datetime.date, optional): Data de referência; None usa a data atual.

    Returns:
        Tuple[datetime.date, datetime.date]: (início inclusivo, fim exclusivo).

    Raises:
        ValueError: Se o mês estiver fora de 1-12 ou for inteiramente futuro.
    """
    if not 1 <= month <= 12:
        raise ValueError("O mês deve estar entre 1 (janeiro) e 12 (dezembro).")

    reference = today or datetime.date.today()

    start = datetime.date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = datetime.date(year, month, last_day) + datetime.timedelta(days=1)

    if start > reference:
        raise ValueError(
            f"O mês {month}/{year} ainda não começou; não há período observável."
        )

    observable_end = min(end, reference)

    # No primeiro dia do mês o intervalo seria vazio. Devolver isso adiante faz o
    # Earth Engine levantar "Empty date ranges not supported" e, se passasse, o
    # acumulado de zero dia viraria uma produtividade de 0,00 t MS/ha — que o
    # usuário leria como pasto sem produção.
    if observable_end <= start:
        raise ValueError(
            f"O mês {month}/{year} começou hoje; ainda não há dia observável. "
            "Use o mês anterior."
        )

    return start, observable_end


def annual_period(year: int) -> Tuple[datetime.date, datetime.date]:
    """
    Período de um ano calendário, com fim exclusivo.

    Args:
        year (int): Ano de referência.

    Returns:
        Tuple[datetime.date, datetime.date]: (1º de janeiro, 1º de janeiro do ano seguinte).
    """
    return datetime.date(year, 1, 1), datetime.date(year + 1, 1, 1)


def is_partial_month(period_start: datetime.date, period_end: datetime.date) -> bool:
    """
    Se o período cobre menos que o mês calendário inteiro.

    Args:
        period_start (datetime.date): Início do período.
        period_end (datetime.date): Fim exclusivo do período.

    Returns:
        bool: True quando o mês está incompleto.
    """
    last_day = calendar.monthrange(period_start.year, period_start.month)[1]
    full_end = datetime.date(period_start.year, period_start.month, last_day) + datetime.timedelta(days=1)
    return period_end < full_end


def dry_matter_conversion_factors(
    lue: float = GRASS_LUE_MAX_GC_PER_MJ,
    contract: AssetUnitContract = T2G_UGPP_CF_CONTRACT,
) -> Dict[str, float]:
    """
    Cadeia de fatores aplicada ao dado bruto do Time2Graze.

    A escala vem do contrato do asset, e não de uma constante do módulo: os dois
    assets uGPP (`cf` e `prod`) armazenam o mesmo sinal físico em escalas que
    diferem por 10x.

    Args:
        lue (float): Eficiência do uso da radiação adotada, em gC/MJ.
        contract (AssetUnitContract): Contrato do asset efetivamente usado.

    Returns:
        Dict[str, float]: Fatores nomeados, prontos para ir dentro da estimativa.
    """
    return {
        "asset_scale": contract.stored_scale,
        "grass_fraction_or_lue": lue,
        "carbon_to_dry_matter": CARBON_TO_DRY_MATTER,
        "unit_conversion": GRAMS_PER_M2_TO_TONS_PER_HA,
    }


def daily_rate_to_dry_matter_t_ha(
    mean_daily_dn: float,
    days: int,
    lue: float = GRASS_LUE_MAX_GC_PER_MJ,
    contract: AssetUnitContract = T2G_UGPP_CF_CONTRACT,
) -> float:
    """
    Converte a média diária bruta do uGPP em matéria seca acumulada no período.

    Esta é a aritmética que o teste de pixel sintético verifica: dado um DN
    conhecido e um número de dias conhecido, o resultado em t MS/ha é determinístico.

    Args:
        mean_daily_dn (float): Média das observações válidas, em DN bruto.
        days (int): Número de dias do período de acumulação.
        lue (float): Eficiência do uso da radiação adotada, em gC/MJ.
        contract (AssetUnitContract): Contrato do asset de origem (define a escala).

    Returns:
        float: Matéria seca acumulada, em t MS/ha.
    """
    factors = dry_matter_conversion_factors(lue, contract)
    daily_dry_matter_g_m2 = (
        mean_daily_dn
        * factors["asset_scale"]
        * factors["grass_fraction_or_lue"]
        * factors["carbon_to_dry_matter"]
    )
    return daily_dry_matter_g_m2 * days * factors["unit_conversion"]


def uncertainty_bounds(
    value_per_ha: Optional[float],
    lue: float = GRASS_LUE_MAX_GC_PER_MJ,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Intervalo de incerteza derivado da faixa publicada de LUEmax.

    A estimativa é linear em LUEmax, então o intervalo é a razão entre os extremos
    da faixa e o valor adotado.

    Args:
        value_per_ha (float, optional): Valor central, por hectare.
        lue (float): LUEmax adotado na estimativa.

    Returns:
        Tuple[float | None, float | None]: (limite inferior, limite superior).
    """
    if value_per_ha is None:
        return None, None
    return (
        value_per_ha * GRASS_LUE_MIN_GC_PER_MJ / lue,
        value_per_ha * GRASS_LUE_UPPER_GC_PER_MJ / lue,
    )


# -----------------------------------------------------------------------------
# Fonte mensal: Time2Graze / uGPP
# -----------------------------------------------------------------------------

def _ugpp_collection(
    roi: ee.Geometry,
    start: datetime.date,
    end: datetime.date,
    contract: AssetUnitContract,
) -> ee.ImageCollection:
    """
    Coleção uGPP de um asset, filtrada por região, período e datas problemáticas.

    Args:
        roi (ee.Geometry): Região de interesse.
        start (datetime.date): Início inclusivo.
        end (datetime.date): Fim exclusivo.
        contract (AssetUnitContract): Contrato do asset a consultar.

    Returns:
        ee.ImageCollection: Coleção filtrada.
    """
    collection = ee.ImageCollection(contract.asset_id)

    for bad_date in contract.known_bad_dates:
        next_day = (datetime.date.fromisoformat(bad_date) + datetime.timedelta(days=1)).isoformat()
        collection = collection.filter(ee.Filter.date(bad_date, next_day).Not())

    return collection.filterBounds(roi).filterDate(start.isoformat(), end.isoformat())


def select_ugpp_source(
    roi: ee.Geometry,
    period_start: datetime.date,
    period_end: datetime.date,
) -> Optional[tuple]:
    """
    Escolhe qual asset uGPP responde pelo período, junto com o seu contrato.

    Os dois assets guardam o mesmo sinal em escalas diferentes, então a escolha do
    asset e a escala andam sempre juntas. A preferência é pelo `prod` (fluxo de
    produção corrente, cobre as datas mais recentes); o `cf` responde pelo
    histórico. Vence o que tiver mais cenas no período.

    Args:
        roi (ee.Geometry): Região de interesse.
        period_start (datetime.date): Início inclusivo do período.
        period_end (datetime.date): Fim exclusivo do período.

    Returns:
        tuple | None: (contrato, coleção filtrada, número de cenas), ou None quando
        nenhum dos assets tem cena no período.
    """
    best = None

    for contract in T2G_UGPP_CONTRACTS:
        collection = _ugpp_collection(roi=roi, start=period_start, end=period_end, contract=contract)
        scene_count = int(collection.size().getInfo())

        if scene_count == 0:
            continue
        if best is None or scene_count > best[2]:
            best = (contract, collection, scene_count)

    return best


def monthly_productivity_image(
    roi: ee.Geometry,
    period_start: datetime.date,
    period_end: datetime.date,
    mask: PastureMask,
    lue: float = GRASS_LUE_MAX_GC_PER_MJ,
) -> Optional[Tuple[ee.Image, ee.Image, int]]:
    """
    Imagem de produtividade acumulada no período, em t MS/ha, já mascarada.

    Args:
        roi (ee.Geometry): Região de interesse.
        period_start (datetime.date): Início inclusivo do período.
        period_end (datetime.date): Fim exclusivo do período.
        mask (PastureMask): Máscara de pastagem a aplicar.
        lue (float): LUEmax adotado, em gC/MJ.

    Returns:
        tuple | None: (imagem em t MS/ha nomeada 'dm_t_ha', imagem de contagem de
        observações válidas por pixel, número de cenas no período, contrato do asset
        usado), ou None quando nenhum asset tem cena para o período.
    """
    source = select_ugpp_source(roi=roi, period_start=period_start, period_end=period_end)
    if source is None:
        return None

    contract, collection, scene_count = source

    days = (period_end - period_start).days
    factors = dry_matter_conversion_factors(lue, contract)

    daily_dry_matter = (
        collection.mean()
        .select(contract.band)
        .multiply(factors["asset_scale"])
        .multiply(factors["grass_fraction_or_lue"])
        .multiply(factors["carbon_to_dry_matter"])
    )

    accumulated = (
        daily_dry_matter
        .multiply(days)
        .multiply(factors["unit_conversion"])
        .updateMask(mask.image)
        .clip(roi)
        .rename("dm_t_ha")
    )

    valid_observations = (
        collection.select(contract.band)
        .count()
        .updateMask(mask.image)
        .clip(roi)
        .rename("valid_obs")
    )

    return accumulated, valid_observations, scene_count, contract


def _reduce_per_ha_and_total(
    image: ee.Image,
    roi: ee.Geometry,
    scale: float,
    band: str,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Reduz uma imagem "por hectare" para média, total e área válida.

    O total usa `ee.Image.pixelArea()`, jamais um multiplicador fixo por resolução:
    a área real do pixel varia com a latitude e com a projeção do asset.

    Args:
        image (ee.Image): Imagem cujos valores estão em unidade por hectare.
        roi (ee.Geometry): Região de interesse.
        scale (float): Escala de redução, em metros.
        band (str): Nome da banda de valor.

    Returns:
        Tuple[float | None, float | None, float | None]: (valor médio por hectare,
        valor total na área válida, área válida em hectares).
    """
    pixel_hectares = ee.Image.pixelArea().divide(10_000)

    mean_stats = image.rename(band).reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=roi,
        scale=scale,
        maxPixels=1e13,
    ).getInfo()

    summed = (
        image.multiply(pixel_hectares).rename("total")
        .addBands(pixel_hectares.updateMask(image.mask()).rename("valid_ha"))
    )

    sum_stats = summed.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=roi,
        scale=scale,
        maxPixels=1e13,
    ).getInfo()

    mean_value = mean_stats.get(band)
    total_value = sum_stats.get("total")
    valid_area = sum_stats.get("valid_ha")

    return (
        None if mean_value is None else float(mean_value),
        None if total_value is None else float(total_value),
        None if valid_area is None else float(valid_area),
    )


def estimate_monthly_productivity(
    roi: ee.Geometry,
    year: int,
    month: int,
    mask: Optional[PastureMask] = None,
    lue: float = GRASS_LUE_MAX_GC_PER_MJ,
    today: Optional[datetime.date] = None,
    raise_on_missing: bool = False,
    min_period_days: int = MIN_OBSERVABLE_DAYS,
) -> Optional[BiomassEstimate]:
    """
    Produtividade mensal de matéria seca estimada, em t MS/ha/mês.

    Sem dado para o mês pedido, devolve None (ou levanta `NoDataForPeriodError`).
    Nunca cai para o MapBiomas anual: são métricas diferentes, e trocar uma pela
    outra sem dizer é o erro que esta arquitetura existe para impedir.

    Args:
        roi (ee.Geometry): Região de interesse (polígono do imóvel).
        year (int): Ano do mês a acumular.
        month (int): Mês a acumular (1-12).
        mask (PastureMask, optional): Máscara de pastagem; None constrói a oficial.
        lue (float): LUEmax adotado, em gC/MJ.
        today (datetime.date, optional): Data de referência para truncar mês corrente.
        raise_on_missing (bool): Se True, levanta em vez de devolver None.
        min_period_days (int): Dias mínimos de mês corrido para que a estimativa
            seja emitida; abaixo disso o mês é curto demais para ser chamado de
            produtividade mensal.

    Returns:
        BiomassEstimate | None: Estimativa com metadados completos, ou None.

    Raises:
        NoDataForPeriodError: Quando `raise_on_missing` e não há cena no período.
        ImplausibleEstimateError: Se o valor estourar o envelope agronômico.
    """
    try:
        period_start, period_end = monthly_period(year=year, month=month, today=today)
    except ValueError as error:
        if raise_on_missing:
            raise NoDataForPeriodError(str(error)) from error
        log_warning(f"estimate_monthly_productivity: {error}")
        return None

    elapsed_days = (period_end - period_start).days
    if elapsed_days < min_period_days:
        message = (
            f"O mês {MONTH_NAMES[month]}/{year} tem apenas {elapsed_days} dia(s) "
            f"corridos (mínimo {min_period_days}); é curto demais para ser "
            "comparado a um mês inteiro. Use o mês anterior."
        )
        log_warning(f"estimate_monthly_productivity: {message}")
        if raise_on_missing:
            raise NoDataForPeriodError(message)
        return None

    pasture_mask = mask or build_pasture_mask(roi=roi, strategy="official")

    result = monthly_productivity_image(
        roi=roi,
        period_start=period_start,
        period_end=period_end,
        mask=pasture_mask,
        lue=lue,
    )

    if result is None:
        message = (
            f"Não há estimativa mensal de produtividade para {MONTH_NAMES[month]}/{year}: "
            f"nenhum asset do {T2G_UGPP_CF_CONTRACT.producer} tem cena para este período "
            f"nesta região. Cobertura conhecida: "
            f"{T2G_UGPP_PROD_CONTRACT.producer_version} {T2G_UGPP_PROD_CONTRACT.temporal_coverage}; "
            f"{T2G_UGPP_CF_CONTRACT.producer_version} {T2G_UGPP_CF_CONTRACT.temporal_coverage}. "
            f"{T2G_UGPP_CF_CONTRACT.spatial_coverage}"
        )
        log_warning(f"estimate_monthly_productivity: {message}")
        if raise_on_missing:
            raise NoDataForPeriodError(message)
        return None

    accumulated, valid_observations, scene_count, contract = result
    contract.require(minimum_status="inferred")

    value_per_ha, total_value, valid_area_ha = _reduce_per_ha_and_total(
        image=accumulated,
        roi=roi,
        scale=contract.nominal_resolution_m,
        band="dm_t_ha",
    )

    observation_stats = valid_observations.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=roi,
        scale=contract.nominal_resolution_m,
        maxPixels=1e13,
    ).getInfo()

    mean_valid_observations = observation_stats.get("valid_obs")
    valid_fraction = (
        None if mean_valid_observations is None
        else min(1.0, float(mean_valid_observations) / scene_count)
    )

    report = ValidationReport()
    report.merge(contract_quality_flags(contract))
    report.merge(observation_quality_flags(valid_fraction))
    report.merge(pasture_mask.quality_flags)
    report.merge(assert_within_envelope("monthly_dry_matter_productivity", value_per_ha))

    report.limitations.append(
        "Estimativa de produtividade (quanto o pasto produziu no período); não "
        "representa a biomassa em pé nem a forragem disponível para pastejo."
    )
    report.limitations.append(
        f"Acumulação por extrapolação: média das observações válidas x {(period_end - period_start).days} "
        f"dias, sobre {scene_count} cena(s) no período."
    )
    if contract.verification_status == "inferred":
        report.limitations.append(
            "A escala do produto de origem foi inferida por validação cruzada e ainda "
            "não foi confirmada na documentação do produtor."
        )

    if is_partial_month(period_start, period_end):
        report.merge(["partial_month"])
        report.limitations.append(
            f"Mês incompleto: período encerrado em {period_end.strftime('%d/%m/%Y')}."
        )

    lower, upper = uncertainty_bounds(value_per_ha, lue=lue)

    return BiomassEstimate(
        metric_type="monthly_dry_matter_productivity",
        source=f"{contract.producer} uGPP",
        source_version=contract.producer_version,
        period_start=period_start,
        period_end=period_end,
        temporal_support="monthly",
        value_per_ha=value_per_ha,
        total_value=total_value,
        unit_per_ha="t_DM_ha_month",
        total_unit="t_DM_month",
        raster_resolution_m=contract.nominal_resolution_m,
        effective_mask_resolution_m=pasture_mask.metadata.resolution_m,
        pasture_mask_source=pasture_mask.metadata.source,
        pasture_mask_reference_year=pasture_mask.metadata.reference_year,
        pasture_mask=pasture_mask.metadata,
        valid_area_ha=valid_area_ha,
        valid_observation_fraction=valid_fraction,
        lower_bound_per_ha=lower,
        upper_bound_per_ha=upper,
        uncertainty_method=UNCERTAINTY_METHOD,
        conversion_factors=dry_matter_conversion_factors(lue, contract),
        model_version=MONTHLY_MODEL_VERSION,
        quality_flags=report.quality_flags,
        limitations=report.limitations,
    )


def latest_monthly_productivity(
    roi: ee.Geometry,
    mask: Optional[PastureMask] = None,
    lue: float = GRASS_LUE_MAX_GC_PER_MJ,
    today: Optional[datetime.date] = None,
    lookback_months: int = _LATEST_MONTH_LOOKBACK,
) -> Optional[BiomassEstimate]:
    """
    Estimativa mensal mais recente disponível, com o seu período explícito.

    Percorre os meses para trás até achar um com dado. A estimativa devolvida diz
    a que mês se refere — não há substituição silenciosa do mês pedido.

    Args:
        roi (ee.Geometry): Região de interesse.
        mask (PastureMask, optional): Máscara de pastagem reaproveitada entre tentativas.
        lue (float): LUEmax adotado, em gC/MJ.
        today (datetime.date, optional): Data de referência.
        lookback_months (int): Quantos meses procurar para trás.

    Returns:
        BiomassEstimate | None: Estimativa do mês mais recente com dado, ou None.
    """
    reference = today or datetime.date.today()
    pasture_mask = mask or build_pasture_mask(roi=roi, strategy="official")

    year, month = reference.year, reference.month

    for _ in range(lookback_months):
        estimate = estimate_monthly_productivity(
            roi=roi, year=year, month=month, mask=pasture_mask, lue=lue, today=reference
        )
        if estimate is not None:
            return estimate

        month -= 1
        if month == 0:
            year, month = year - 1, 12

    log_warning(
        f"latest_monthly_productivity: nenhum mês com dado nos últimos "
        f"{lookback_months} meses para esta região."
    )
    return None


# -----------------------------------------------------------------------------
# Fonte anual: MapBiomas
# -----------------------------------------------------------------------------

def available_annual_years() -> List[int]:
    """
    Anos disponíveis no asset anual do MapBiomas, lidos das bandas.

    Returns:
        List[int]: Anos em ordem crescente.
    """
    bands = ee.Image(MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.asset_id).bandNames().getInfo()
    prefix = MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.band.split("{")[0]
    return sorted(
        int(band.replace(prefix, "")) for band in bands if band.startswith(prefix)
    )


def annual_productivity_band(year: int) -> str:
    """
    Nome da banda anual do MapBiomas para o ano pedido.

    A seleção é sempre por NOME. Selecionar por índice (`select(year - 2000)`) só
    funciona enquanto a primeira banda da coleção for `biomass_2000`.

    Args:
        year (int): Ano desejado.

    Returns:
        str: Nome da banda, por exemplo "biomass_2024".
    """
    return MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.band.format(year=year)


def annual_productivity_image(roi: ee.Geometry, year: int, mask: Optional[PastureMask] = None) -> ee.Image:
    """
    Imagem anual de produtividade do MapBiomas, em t MS/ha/ano.

    Os valores de pixel já estão na unidade final: não há escala a aplicar nem
    multiplicação por área (isso é feito só no total, via pixelArea).

    Args:
        roi (ee.Geometry): Região de interesse.
        year (int): Ano desejado.
        mask (PastureMask, optional): Máscara adicional a aplicar.

    Returns:
        ee.Image: Imagem em t MS/ha/ano, nomeada 'dm_t_ha_year'.

    Raises:
        ValueError: Se o ano não existir no asset.
    """
    years = available_annual_years()
    if year not in years:
        raise ValueError(
            f"O ano {year} não existe no {MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.producer_version}. "
            f"Anos disponíveis: {years[0]} a {years[-1]}."
        )

    image = (
        ee.Image(MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.asset_id)
        .select(annual_productivity_band(year))
        .rename("dm_t_ha_year")
    )

    if mask is not None:
        image = image.updateMask(mask.image)

    return image.clip(roi)


def estimate_annual_productivity(
    roi: ee.Geometry,
    year: Optional[int] = None,
    mask: Optional[PastureMask] = None,
) -> BiomassEstimate:
    """
    Produtividade anual de matéria seca estimada, em t MS/ha/ano (MapBiomas).

    Esta é a série histórica e a linha de base do sistema. Ela nunca deve ser
    apresentada como estimativa do mês corrente.

    Args:
        roi (ee.Geometry): Região de interesse.
        year (int, optional): Ano desejado; None usa o mais recente disponível.
        mask (PastureMask, optional): Máscara adicional; o produto já é restrito
            à pastagem mapeada pelo MapBiomas no ano.

    Returns:
        BiomassEstimate: Estimativa anual com metadados completos.

    Raises:
        ValueError: Se o ano pedido não existir no asset.
        ImplausibleEstimateError: Se o valor estourar o envelope agronômico.
    """
    MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.require(minimum_status="documented")

    years = available_annual_years()
    target_year = year if year is not None else years[-1]

    image = annual_productivity_image(roi=roi, year=target_year, mask=mask)
    period_start, period_end = annual_period(target_year)

    value_per_ha, total_value, valid_area_ha = _reduce_per_ha_and_total(
        image=image,
        roi=roi,
        scale=MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.nominal_resolution_m,
        band="dm_t_ha_year",
    )

    if mask is not None:
        mask_metadata = mask.metadata
        mask_source = mask_metadata.source
        mask_year = mask_metadata.reference_year
        mask_resolution = mask_metadata.resolution_m
        mask_flags = mask.quality_flags
    else:
        mask_source = f"{MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.producer} (pastagem do próprio produto)"
        mask_year = target_year
        mask_resolution = MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.nominal_resolution_m
        mask_metadata = None
        mask_flags = []

    report = ValidationReport()
    report.merge(contract_quality_flags(MAPBIOMAS_PASTURE_BIOMASS_CONTRACT))
    report.merge(mask_flags)
    report.merge(assert_within_envelope("annual_dry_matter_productivity", value_per_ha))

    report.limitations.append(
        "Produtividade ANUAL consolidada; é linha de base histórica, não a condição "
        "atual da pastagem."
    )

    current_year = datetime.date.today().year
    if target_year < current_year:
        report.merge(["reference_year_lag"])
        report.limitations.append(
            f"Defasagem de {current_year - target_year} ano(s): {target_year} é o ano mais "
            "recente consolidado pelo MapBiomas."
        )

    return BiomassEstimate(
        metric_type="annual_dry_matter_productivity",
        source=f"{MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.producer} - biomassa de pastagem",
        source_version=MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.producer_version,
        period_start=period_start,
        period_end=period_end,
        temporal_support="annual",
        value_per_ha=value_per_ha,
        total_value=total_value,
        unit_per_ha="t_DM_ha_year",
        total_unit="t_DM_year",
        raster_resolution_m=MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.nominal_resolution_m,
        effective_mask_resolution_m=mask_resolution,
        pasture_mask_source=mask_source,
        pasture_mask_reference_year=mask_year,
        pasture_mask=mask_metadata,
        valid_area_ha=valid_area_ha,
        valid_observation_fraction=None,
        lower_bound_per_ha=None,
        upper_bound_per_ha=None,
        uncertainty_method=None,
        conversion_factors={"asset_scale": MAPBIOMAS_PASTURE_BIOMASS_CONTRACT.stored_scale},
        model_version=ANNUAL_MODEL_VERSION,
        quality_flags=report.quality_flags,
        limitations=report.limitations,
    )


def annualize_monthly_series(estimates: List[BiomassEstimate]) -> BiomassEstimate:
    """
    Soma uma série mensal em uma produtividade anual comparável.

    É o único caminho legítimo entre a fonte mensal e qualquer cálculo em base
    anual: exige os 12 meses e recusa séries incompletas ou com buracos.

    Args:
        estimates (List[BiomassEstimate]): Estimativas mensais consecutivas.

    Returns:
        BiomassEstimate: Estimativa anual com suporte temporal 'annual'.

    Raises:
        ValueError: Se a série não tiver 12 meses consecutivos da mesma fonte.
    """
    if len(estimates) != 12:
        raise ValueError(
            f"A anualização exige 12 meses; foram informados {len(estimates)}. "
            "Uma série incompleta não pode virar produtividade anual."
        )

    for estimate in estimates:
        if estimate.metric_type != "monthly_dry_matter_productivity":
            raise ValueError(
                f"A série deve conter apenas 'monthly_dry_matter_productivity'; "
                f"encontrado '{estimate.metric_type}'."
            )

    ordered = sorted(estimates, key=lambda item: item.period_start)

    for previous, current in zip(ordered, ordered[1:]):
        if previous.period_end != current.period_start:
            raise ValueError(
                f"Buraco na série entre {previous.period_end} e {current.period_start}: "
                "a anualização exige meses consecutivos."
            )

    values = [estimate.value_per_ha for estimate in ordered]
    if any(value is None for value in values):
        raise ValueError("A série contém meses sem valor estimado; não é anualizável.")

    total_per_ha = sum(values)
    totals = [estimate.total_value for estimate in ordered]
    total_value = None if any(item is None for item in totals) else sum(totals)

    lower_values = [estimate.lower_bound_per_ha for estimate in ordered]
    upper_values = [estimate.upper_bound_per_ha for estimate in ordered]
    lower = None if any(item is None for item in lower_values) else sum(lower_values)
    upper = None if any(item is None for item in upper_values) else sum(upper_values)

    report = ValidationReport()
    for estimate in ordered:
        report.merge(estimate.quality_flags)
    report.merge(["annualized_from_monthly_series"])
    report.merge(assert_within_envelope("annual_dry_matter_productivity", total_per_ha))

    reference = ordered[0]
    valid_fractions = [
        estimate.valid_observation_fraction
        for estimate in ordered
        if estimate.valid_observation_fraction is not None
    ]

    return BiomassEstimate(
        metric_type="annual_dry_matter_productivity",
        source=reference.source,
        source_version=reference.source_version,
        period_start=ordered[0].period_start,
        period_end=ordered[-1].period_end,
        temporal_support="annual",
        value_per_ha=total_per_ha,
        total_value=total_value,
        unit_per_ha="t_DM_ha_year",
        total_unit="t_DM_year",
        raster_resolution_m=reference.raster_resolution_m,
        effective_mask_resolution_m=reference.effective_mask_resolution_m,
        pasture_mask_source=reference.pasture_mask_source,
        pasture_mask_reference_year=reference.pasture_mask_reference_year,
        pasture_mask=reference.pasture_mask,
        valid_area_ha=reference.valid_area_ha,
        valid_observation_fraction=(
            sum(valid_fractions) / len(valid_fractions) if valid_fractions else None
        ),
        lower_bound_per_ha=lower,
        upper_bound_per_ha=upper,
        uncertainty_method=reference.uncertainty_method if lower is not None else None,
        conversion_factors=reference.conversion_factors,
        model_version=f"{MONTHLY_MODEL_VERSION}+annualized",
        quality_flags=report.quality_flags,
        limitations=[
            "Produtividade anual obtida pela soma de 12 estimativas mensais, não pelo "
            "produto anual consolidado do MapBiomas.",
        ],
    )
