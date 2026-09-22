"""Série histórica anual de produtividade (2000-2024), calculada on-the-fly.

Issue #112. A fonte é o GPP bruto anual do Global Pasture Watch
(`ggpp-30m/v1/ugpp_m`, banda `gc_m2`, uma imagem por ano de 2000 a 2024),
recortado pela máscara de pastagem do imóvel.

A cadeia de conversão é a mesma do script oficial do GPW/LAPIG, e a mesma
estrutura do pipeline mensal do Time2Graze:

    uGPP acumulado no ano (banda `gc_m2`)
      x grass_fraction_or_lue  -> gC/m²/ano
      x carbon_to_dry_matter   -> g MS/m²/ano
      x unit_conversion        -> t MS/ha/ano

O nome da banda (`gc_m2`) sugere carbono já convertido, mas **o LUEmax ainda
precisa ser aplicado** — é o que o script de referência faz. O LUEmax de 0,50
gC/m²/dia/MJ é o de Urochloa cultivada no Brasil; o 0,86 do MOD17A2 é global e
superestima em ~97% por aqui.

O fator carbono -> matéria seca tem duas variantes documentadas: 2,3 (MapBiomas
Brasil, padrão aqui) e 2,7 (IPCC). A diferença entre elas é o intervalo de
incerteza.

Além das estatísticas agregadas, o módulo exporta **todos os pixels** da
propriedade para zarr, persistido no S3 em produção e em `tmp/` em
desenvolvimento, pela mesma via do cache de classificação de pastagem.
"""

import datetime
import time

from typing import Dict, List, Optional, Tuple

import ee
import xarray as xr

from agno.utils.log import log_info, log_warning

from app.schemas.biomass_schemas import BiomassEstimate
from app.services.geospatial.biomass.biomass_validation import (
    CARBON_TO_DRY_MATTER_IPCC,
    CARBON_TO_DRY_MATTER_MAPBIOMAS_BR,
    GPW_UGPP_HISTORICAL_CONTRACT,
    GRAMS_PER_M2_TO_TONS_PER_HA,
    GRASS_LUE_MAX_GC_PER_MJ,
    ValidationReport,
    assert_within_envelope,
    contract_quality_flags,
)
from app.services.geospatial.biomass.pasture_mask import PastureMask, build_pasture_mask


HISTORICAL_MODEL_VERSION = "historical-productivity-v1"

UNCERTAINTY_METHOD = (
    "variantes documentadas do fator carbono -> matéria seca (2,3 MapBiomas Brasil "
    "a 2,7 IPCC)"
)

# Escala de redução/exportação: a grade nativa do produto (~27,8 m).
HISTORICAL_SCALE_M = 30.0

# Sentinela gravado no zarr para "pixel fora da máscara de pastagem".
_MASK_VALUE = -32768

# Valor que o Xee entende como "sem dado" no transfer, e que ele converte em NaN.
# PRECISA ser diferente de `_MASK_VALUE`: usar o mesmo número nos dois papéis faz o
# Xee transformar o nosso sentinela em NaN, e o cast para int16 transforma o NaN em
# 0 — o pixel sem pastagem passaria a valer zero de produtividade. Como a grade é
# totalmente preenchida por `unmask`, este valor nunca ocorre de fato.
_XEE_MASK_VALUE = -9999


def historical_conversion_factors(
    lue: float = GRASS_LUE_MAX_GC_PER_MJ,
    carbon_to_dry_matter: float = CARBON_TO_DRY_MATTER_MAPBIOMAS_BR,
) -> Dict[str, float]:
    """
    Cadeia de fatores aplicada ao uGPP anual, igual à do script oficial GPW/LAPIG.

    Args:
        lue (float): LUEmax adotado, em gC/m²/dia/MJ.
        carbon_to_dry_matter (float): Fator carbono -> matéria seca (2,3 ou 2,7).

    Returns:
        Dict[str, float]: Fatores nomeados, prontos para ir dentro da estimativa.
    """
    return {
        "asset_scale": GPW_UGPP_HISTORICAL_CONTRACT.stored_scale,
        "grass_fraction_or_lue": lue,
        "carbon_to_dry_matter": carbon_to_dry_matter,
        "unit_conversion": GRAMS_PER_M2_TO_TONS_PER_HA,
    }


def gpp_to_dry_matter_t_ha(
    ugpp_per_m2: float,
    lue: float = GRASS_LUE_MAX_GC_PER_MJ,
    carbon_to_dry_matter: float = CARBON_TO_DRY_MATTER_MAPBIOMAS_BR,
) -> float:
    """
    Converte o uGPP anual acumulado em matéria seca (t MS/ha/ano).

    Aritmética pura, sem Earth Engine — é o que o teste de pixel sintético verifica.
    Reproduz `DRY_BIOMASS_FACTOR = LUEmax * IPCC_FACTOR * UNIT_CONVERSION` do script
    oficial do GPW/LAPIG.

    Args:
        ugpp_per_m2 (float): uGPP acumulado no ano (banda `gc_m2`).
        lue (float): LUEmax adotado, em gC/m²/dia/MJ.
        carbon_to_dry_matter (float): Fator carbono -> matéria seca (2,3 ou 2,7).

    Returns:
        float: Produtividade anual de matéria seca, em t MS/ha/ano.
    """
    factors = historical_conversion_factors(lue, carbon_to_dry_matter)
    return (
        ugpp_per_m2
        * factors["asset_scale"]
        * factors["grass_fraction_or_lue"]
        * factors["carbon_to_dry_matter"]
        * factors["unit_conversion"]
    )


def historical_uncertainty_bounds(
    value_per_ha: Optional[float],
    carbon_to_dry_matter: float = CARBON_TO_DRY_MATTER_MAPBIOMAS_BR,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Intervalo entre as duas variantes documentadas do fator carbono -> matéria seca.

    A estimativa é linear nesse fator, então o intervalo é a razão entre os
    extremos (2,3 e 2,7) e o valor adotado. Com o padrão 2,3 o intervalo é
    assimétrico para cima, que é a realidade: o fator do IPCC é maior que o
    brasileiro.

    Args:
        value_per_ha (float, optional): Valor central, por hectare.
        carbon_to_dry_matter (float): Fator adotado na estimativa.

    Returns:
        Tuple[float | None, float | None]: (limite inferior, limite superior).
    """
    if value_per_ha is None:
        return None, None

    def _scaled(target: float) -> float:
        # Quando o fator adotado É o extremo, o limite tem de ser exatamente o valor
        # central: a ida e volta por ponto flutuante devolveria 30,000000000000004 e
        # o intervalo deixaria de conter o próprio valor que descreve.
        if target == carbon_to_dry_matter:
            return value_per_ha
        return value_per_ha * target / carbon_to_dry_matter

    return _scaled(CARBON_TO_DRY_MATTER_MAPBIOMAS_BR), _scaled(CARBON_TO_DRY_MATTER_IPCC)


def available_historical_years() -> List[int]:
    """
    Anos disponíveis na coleção histórica do Global Pasture Watch.

    Returns:
        List[int]: Anos em ordem crescente.
    """
    indexes = (
        ee.ImageCollection(GPW_UGPP_HISTORICAL_CONTRACT.asset_id)
        .aggregate_array("system:index")
        .getInfo()
    )
    return sorted(int(index) for index in indexes if str(index).isdigit())


def historical_productivity_image(
    roi: ee.Geometry,
    year: int,
    mask: PastureMask,
    carbon_to_dry_matter: float = CARBON_TO_DRY_MATTER_MAPBIOMAS_BR,
) -> Optional[ee.Image]:
    """
    Imagem de produtividade anual em t MS/ha/ano para um ano da série histórica.

    Args:
        roi (ee.Geometry): Região de interesse.
        year (int): Ano desejado.
        mask (PastureMask): Máscara de pastagem a aplicar.
        carbon_to_dry_matter (float): Fator carbono -> matéria seca (2,3 ou 2,7).

    Returns:
        ee.Image | None: Imagem nomeada 'dm_t_ha_year', ou None quando o ano não
        tem imagem para a região.
    """
    collection = (
        ee.ImageCollection(GPW_UGPP_HISTORICAL_CONTRACT.asset_id)
        .filterBounds(roi)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
    )

    if int(collection.size().getInfo()) == 0:
        return None

    factors = historical_conversion_factors(carbon_to_dry_matter=carbon_to_dry_matter)

    return (
        collection.first()
        .select(GPW_UGPP_HISTORICAL_CONTRACT.band)
        .multiply(factors["asset_scale"])
        .multiply(factors["grass_fraction_or_lue"])
        .multiply(factors["carbon_to_dry_matter"])
        .multiply(factors["unit_conversion"])
        .updateMask(mask.image)
        .clip(roi)
        .rename("dm_t_ha_year")
    )


def estimate_historical_productivity(
    roi: ee.Geometry,
    year: int,
    mask: Optional[PastureMask] = None,
    carbon_to_dry_matter: float = CARBON_TO_DRY_MATTER_MAPBIOMAS_BR,
) -> Optional[BiomassEstimate]:
    """
    Produtividade anual de matéria seca de um ano da série histórica (2000-2024).

    Args:
        roi (ee.Geometry): Região de interesse (polígono do imóvel).
        year (int): Ano desejado.
        mask (PastureMask, optional): Máscara de pastagem; None constrói a oficial.
        carbon_to_dry_matter (float): Fator carbono -> matéria seca (2,3 ou 2,7).

    Returns:
        BiomassEstimate | None: Estimativa anual com metadados completos, ou None
        quando o ano não tem imagem para a região.

    Raises:
        ImplausibleEstimateError: Se o valor estourar o envelope agronômico.
    """
    from app.services.geospatial.biomass.biomass_productivity import (
        _reduce_per_ha_and_total,
        annual_period,
    )

    GPW_UGPP_HISTORICAL_CONTRACT.require(minimum_status="inferred")

    pasture_mask = mask or build_pasture_mask(roi=roi, strategy="official")
    image = historical_productivity_image(
        roi=roi, year=year, mask=pasture_mask, carbon_to_dry_matter=carbon_to_dry_matter
    )

    if image is None:
        log_warning(
            f"estimate_historical_productivity: sem imagem histórica para {year} "
            f"nesta região. Cobertura: {GPW_UGPP_HISTORICAL_CONTRACT.temporal_coverage}."
        )
        return None

    period_start, period_end = annual_period(year)

    value_per_ha, total_value, valid_area_ha = _reduce_per_ha_and_total(
        image=image, roi=roi, scale=HISTORICAL_SCALE_M, band="dm_t_ha_year"
    )

    report = ValidationReport()
    report.merge(contract_quality_flags(GPW_UGPP_HISTORICAL_CONTRACT))
    report.merge(pasture_mask.quality_flags)
    report.merge(assert_within_envelope("annual_dry_matter_productivity", value_per_ha))

    lower, upper = historical_uncertainty_bounds(value_per_ha, carbon_to_dry_matter)

    return BiomassEstimate(
        metric_type="annual_dry_matter_productivity",
        source=f"{GPW_UGPP_HISTORICAL_CONTRACT.producer} uGPP histórico (on-the-fly)",
        source_version=GPW_UGPP_HISTORICAL_CONTRACT.producer_version,
        period_start=period_start,
        period_end=period_end,
        temporal_support="annual",
        value_per_ha=value_per_ha,
        total_value=total_value,
        unit_per_ha="t_DM_ha_year",
        total_unit="t_DM_year",
        raster_resolution_m=GPW_UGPP_HISTORICAL_CONTRACT.nominal_resolution_m,
        effective_mask_resolution_m=pasture_mask.metadata.resolution_m,
        pasture_mask_source=pasture_mask.metadata.source,
        pasture_mask_reference_year=pasture_mask.metadata.reference_year,
        pasture_mask=pasture_mask.metadata,
        valid_area_ha=valid_area_ha,
        valid_observation_fraction=None,
        lower_bound_per_ha=lower,
        upper_bound_per_ha=upper,
        uncertainty_method=UNCERTAINTY_METHOD,
        conversion_factors=historical_conversion_factors(carbon_to_dry_matter=carbon_to_dry_matter),
        model_version=HISTORICAL_MODEL_VERSION,
        quality_flags=report.quality_flags,
        limitations=[
            "Série histórica calculada on-the-fly com a cadeia do script oficial "
            "GPW/LAPIG (LUEmax de Urochloa x fator carbono -> matéria seca x 0,01).",
            "Validação cruzada contra o MapBiomas em 10 pares imóvel-ano: viés de "
            "-2,4% com o fator 2,3 (MapBiomas Brasil); com o fator 2,7 do IPCC o viés "
            "sobe para +14,5%. O intervalo cobre as duas variantes.",
            f"Resolução do produto: {GPW_UGPP_HISTORICAL_CONTRACT.nominal_resolution_m:g} m. "
            "Não é uma análise de 10 m.",
        ],
    )


def historical_series(
    roi: ee.Geometry,
    start_year: int = 2000,
    end_year: int = 2024,
    mask: Optional[PastureMask] = None,
    carbon_to_dry_matter: float = CARBON_TO_DRY_MATTER_MAPBIOMAS_BR,
) -> List[BiomassEstimate]:
    """
    Série anual completa de produtividade para a propriedade.

    Args:
        roi (ee.Geometry): Região de interesse.
        start_year (int): Primeiro ano da série.
        end_year (int): Último ano da série (inclusivo).
        mask (PastureMask, optional): Máscara reaproveitada entre os anos.
        carbon_to_dry_matter (float): Fator carbono -> matéria seca (2,3 ou 2,7).

    Returns:
        List[BiomassEstimate]: Estimativas anuais, em ordem cronológica; anos sem
        imagem são omitidos.

    Raises:
        ValueError: Se o intervalo pedido estiver fora da cobertura do produto.
    """
    years = available_historical_years()
    if not years:
        raise ValueError("A coleção histórica do Global Pasture Watch está vazia.")

    if start_year > end_year:
        raise ValueError("O ano inicial deve ser anterior ou igual ao ano final.")
    if end_year < years[0] or start_year > years[-1]:
        raise ValueError(
            f"O intervalo {start_year}-{end_year} está fora da cobertura do produto "
            f"({years[0]}-{years[-1]})."
        )

    pasture_mask = mask or build_pasture_mask(roi=roi, strategy="official")

    estimates: List[BiomassEstimate] = []
    for year in years:
        if not start_year <= year <= end_year:
            continue
        estimate = estimate_historical_productivity(
            roi=roi, year=year, mask=pasture_mask,
            carbon_to_dry_matter=carbon_to_dry_matter,
        )
        if estimate is not None:
            estimates.append(estimate)

    log_info(
        f"historical_series: {len(estimates)} ano(s) estimado(s) entre "
        f"{start_year} e {end_year}."
    )
    return estimates


# -----------------------------------------------------------------------------
# Exportação pixel a pixel para zarr + S3
# -----------------------------------------------------------------------------

def utm_crs_for(roi: ee.Geometry) -> str:
    """
    Zona UTM métrica que cobre o imóvel, derivada do seu centroide.

    O produto histórico está em EPSG:4326 (graus). Exportar nessa projeção faria
    `scale` significar graus, e o pixel deixaria de ter 30 m: a grade de saída usa
    a zona UTM correspondente ao imóvel.

    Args:
        roi (ee.Geometry): Região de interesse.

    Returns:
        str: Código EPSG da zona UTM (por exemplo "EPSG:32722").
    """
    centroid = roi.centroid(1).coordinates().getInfo()
    longitude, latitude = float(centroid[0]), float(centroid[1])

    zone = int((longitude + 180) // 6) + 1
    base = 32600 if latitude >= 0 else 32700

    return f"EPSG:{base + zone}"


def historical_pixel_dataset(
    roi: ee.Geometry,
    start_year: int = 2000,
    end_year: int = 2024,
    mask: Optional[PastureMask] = None,
    carbon_to_dry_matter: float = CARBON_TO_DRY_MATTER_MAPBIOMAS_BR,
    scale: float = HISTORICAL_SCALE_M,
) -> xr.Dataset:
    """
    Baixa TODOS os pixels da propriedade, para todos os anos, como um xarray.

    O download usa Xee com grade explícita (a API 0.1.1 exige `crs_transform` +
    `shape_2d` em vez de `scale`/`geometry`). Os valores vêm já convertidos em
    t MS/ha/ano, multiplicados por 1000 e convertidos para int16 — o transfer em
    inteiro é sensivelmente mais rápido que em float32, e a escala de 1/1000
    preserva três casas decimais.

    Args:
        roi (ee.Geometry): Região de interesse.
        start_year (int): Primeiro ano da série.
        end_year (int): Último ano da série (inclusivo).
        mask (PastureMask, optional): Máscara de pastagem a aplicar.
        carbon_to_dry_matter (float): Fator carbono -> matéria seca (2,3 ou 2,7).
        scale (float): Tamanho do pixel na exportação, em metros.

    Returns:
        xr.Dataset: Variável `dm_t_ha_year` (int16, escala 1/1000) com dimensão
        temporal anual, mais os atributos de proveniência. Pixels fora da máscara de
        pastagem trazem o sentinela `mask_value` (-32768), distinto de uma
        produtividade nula legítima.

    Raises:
        ValueError: Se nenhum ano do intervalo tiver imagem para a região.
    """
    from app.services.geospatial.pasture_classification import _utm_grid

    pasture_mask = mask or build_pasture_mask(roi=roi, strategy="official")
    years = [year for year in available_historical_years() if start_year <= year <= end_year]

    images = []
    exported_years: List[int] = []
    for year in years:
        image = historical_productivity_image(
            roi=roi, year=year, mask=pasture_mask,
            carbon_to_dry_matter=carbon_to_dry_matter,
        )
        if image is None:
            continue
        # `unmask(..., sameFootprint=False)` grava o sentinela em TODA a grade: sem
        # ele o pixel sem pastagem chega mascarado, o Xee o entrega como NaN em
        # float32 e o cast para int16 o transforma em 0 — indistinguível de
        # produtividade nula de verdade. O padrão `sameFootprint=True` não basta,
        # porque deixa mascarado tudo que está fora do recorte.
        images.append(
            image.multiply(1000).toInt16().unmask(_MASK_VALUE, False)
            .rename("dm_t_ha_year")
            .set("system:time_start", ee.Date.fromYMD(year, 1, 1).millis())
        )
        exported_years.append(year)

    if not images:
        raise ValueError(
            f"Nenhum ano entre {start_year} e {end_year} tem imagem histórica para esta região."
        )

    collection = ee.ImageCollection(images)

    # O produto histórico é EPSG:4326 (grau), mas a exportação precisa de uma grade
    # métrica para que `scale` signifique metros: usa-se a zona UTM do imóvel.
    crs = utm_crs_for(roi)
    transform, width, height = _utm_grid(roi=roi, crs=crs, scale=int(scale))

    started = time.perf_counter()
    dataset = xr.open_dataset(
        collection,
        engine="ee",
        crs=crs,
        crs_transform=transform,
        shape_2d=(width, height),
        mask_and_scale=False,
        ee_mask_value=_XEE_MASK_VALUE,
    ).load().astype("int16")

    dataset.attrs.update({
        "metric_type": "annual_dry_matter_productivity",
        "unit_per_ha": "t_DM_ha_year",
        "value_scale_factor": 0.001,
        "mask_value": _MASK_VALUE,
        "source_asset": GPW_UGPP_HISTORICAL_CONTRACT.asset_id,
        "source_version": GPW_UGPP_HISTORICAL_CONTRACT.producer_version or "",
        "raster_resolution_m": GPW_UGPP_HISTORICAL_CONTRACT.nominal_resolution_m,
        "effective_mask_resolution_m": pasture_mask.metadata.resolution_m,
        "pasture_mask_source": pasture_mask.metadata.source,
        "pasture_mask_reference_year": pasture_mask.metadata.reference_year or 0,
        "model_version": HISTORICAL_MODEL_VERSION,
        "years": exported_years,
        "exported_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        **{f"factor_{name}": value
           for name, value in historical_conversion_factors(carbon_to_dry_matter=carbon_to_dry_matter).items()},
    })

    log_info(
        f"historical_pixel_dataset: {len(exported_years)} ano(s), grade {width}x{height} "
        f"a {scale:g} m, em {time.perf_counter() - started:.1f}s"
    )
    return dataset


def export_historical_series(
    roi: ee.Geometry,
    feature_id: str,
    start_year: int = 2000,
    end_year: int = 2024,
    mask: Optional[PastureMask] = None,
    carbon_to_dry_matter: float = CARBON_TO_DRY_MATTER_MAPBIOMAS_BR,
    scale: float = HISTORICAL_SCALE_M,
    overwrite: bool = False,
) -> Dict:
    """
    Exporta a série histórica pixel a pixel para zarr (S3 em produção, `tmp/` local).

    Reaproveita a mesma via do cache de classificação de pastagem: em
    `production`/`stagging` o zarr vai para o bucket S3; em `development` fica em
    `tmp/`. Chamadas repetidas para o mesmo imóvel/intervalo/versão reaproveitam o
    que já foi exportado, a menos que `overwrite` seja verdadeiro.

    Args:
        roi (ee.Geometry): Região de interesse.
        feature_id (str): Identificador da feição — compõe a chave de armazenamento.
        start_year (int): Primeiro ano da série.
        end_year (int): Último ano da série (inclusivo).
        mask (PastureMask, optional): Máscara de pastagem a aplicar.
        carbon_to_dry_matter (float): Fator carbono -> matéria seca (2,3 ou 2,7).
        scale (float): Tamanho do pixel na exportação, em metros.
        overwrite (bool): Recalcula e sobrescreve mesmo havendo exportação anterior.

    Returns:
        Dict: {"path", "cached", "years", "n_pixels", "dataset"}.
    """
    from app.services.geospatial.biomass.historical_cache import (
        historical_cache_exists,
        historical_cache_path,
        load_historical_cache,
        save_historical_cache,
    )

    pasture_mask = mask or build_pasture_mask(roi=roi, strategy="official")

    key = historical_cache_key(
        feature_id=feature_id, start_year=start_year, end_year=end_year,
        mask=pasture_mask, carbon_to_dry_matter=carbon_to_dry_matter, scale=scale,
    )
    path = historical_cache_path(key)

    if not overwrite and historical_cache_exists(key):
        dataset = load_historical_cache(key)
        log_info(f"[{feature_id}] série histórica reaproveitada do cache: {path}")
        return {
            "path": path,
            "cached": True,
            "years": list(dataset.attrs.get("years", [])),
            "n_pixels": int(dataset["dm_t_ha_year"].size),
            "dataset": dataset,
        }

    dataset = historical_pixel_dataset(
        roi=roi, start_year=start_year, end_year=end_year, mask=pasture_mask,
        carbon_to_dry_matter=carbon_to_dry_matter, scale=scale,
    )
    save_historical_cache(key, dataset)

    log_info(
        f"[{feature_id}] série histórica exportada para {path} "
        f"({dataset['dm_t_ha_year'].size} pixels)"
    )
    return {
        "path": path,
        "cached": False,
        "years": list(dataset.attrs.get("years", [])),
        "n_pixels": int(dataset["dm_t_ha_year"].size),
        "dataset": dataset,
    }


def historical_cache_key(
    feature_id: str,
    start_year: int,
    end_year: int,
    mask: PastureMask,
    carbon_to_dry_matter: float = CARBON_TO_DRY_MATTER_MAPBIOMAS_BR,
    scale: float = HISTORICAL_SCALE_M,
) -> str:
    """
    Chave de armazenamento da série histórica.

    Inclui a versão do modelo, os fatores de conversão, a máscara e a escala: mudar
    qualquer um deles gera uma exportação nova em vez de servir a antiga.

    Args:
        feature_id (str): Identificador da feição.
        start_year (int): Primeiro ano da série.
        end_year (int): Último ano da série.
        mask (PastureMask): Máscara de pastagem usada.
        carbon_to_dry_matter (float): Fator carbono -> matéria seca (2,3 ou 2,7).
        scale (float): Tamanho do pixel na exportação, em metros.

    Returns:
        str: Chave determinística, segura para nome de arquivo.
    """
    import hashlib
    import json

    payload = {
        "feature_id": feature_id,
        "years": [start_year, end_year],
        "mask": mask.signature(),
        "factors": historical_conversion_factors(carbon_to_dry_matter=carbon_to_dry_matter),
        "scale": scale,
        "model_version": HISTORICAL_MODEL_VERSION,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]

    safe_feature_id = feature_id.replace(",", "_").replace(" ", "_").replace("/", "_")
    return f"{safe_feature_id}_{start_year}_{end_year}_{digest}"
