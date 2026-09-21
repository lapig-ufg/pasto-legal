"""Contratos de unidade dos assets, envelopes agronômicos e guardas de coerência.

Este módulo é a única fonte de verdade sobre "o que cada asset significa". Nenhum
fator de conversão pode ser escrito em outro módulo: todos vivem em um
`AssetUnitContract`, com unidade nativa, escala, cadência, política de dado
faltante, versão do produtor e — o ponto principal — um `verification_status`
que diz se aquilo foi confirmado na documentação do produtor ou apenas inferido.

Também guarda as regras que impedem os erros de categoria:
  * `assert_annualizable` bloqueia o cálculo de UA sobre métrica mensal;
  * `assert_within_envelope` rejeita números agronomicamente impossíveis;
  * `build_cache_key` inclui geometria, versão do modelo e fatores, para que uma
    mudança de fator invalide o cache em vez de servir um número velho.
"""

import hashlib
import json

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple


class BiomassValidationError(ValueError):
    """Erro base das validações de biomassa."""


class UnverifiedUnitContractError(BiomassValidationError):
    """O contrato de unidade do asset não está verificado o bastante para o uso pedido."""


class IncompatibleTemporalSupportError(BiomassValidationError):
    """A métrica não tem suporte temporal compatível com o cálculo pedido."""


class ImplausibleEstimateError(BiomassValidationError):
    """O valor estimado está fora do envelope agronômico da métrica."""


class NoDataForPeriodError(BiomassValidationError):
    """Não há observação válida para o período pedido — e nenhum substituto é aceitável."""


@dataclass(frozen=True)
class AssetUnitContract:
    """
    Contrato formal de um asset: o que ele armazena e como converter.

    Nenhuma fórmula pode usar um fator que não esteja aqui. `verification_status`
    assume:
      * "documented" - unidade e escala confirmadas na documentação do produtor;
      * "inferred"   - unidade e escala derivadas de evidência empírica reproduzível
                       (registrada em `evidence`), ainda sem confirmação do produtor;
      * "unverified" - sem confirmação nem evidência suficiente; não pode gerar número.
    """
    asset_id: str
    band: str
    dtype: str
    stored_scale: float
    native_unit: str
    temporal_support: str
    nominal_resolution_m: float
    observation_cadence_days: Optional[float]
    missing_data_policy: str
    producer: str
    producer_version: Optional[str]
    documentation_url: Optional[str]
    verification_status: str
    verified_on: Optional[date] = None
    spatial_coverage: str = "não documentada"
    temporal_coverage: str = "não documentada"
    known_bad_dates: Tuple[str, ...] = ()
    evidence: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()

    def require(self, minimum_status: str = "inferred") -> None:
        """
        Garante que o contrato atinja o nível mínimo de verificação exigido.

        Args:
            minimum_status (str): "documented" ou "inferred".

        Raises:
            UnverifiedUnitContractError: Se o contrato estiver abaixo do exigido.
        """
        ranking = {"unverified": 0, "inferred": 1, "documented": 2}
        if ranking[self.verification_status] < ranking[minimum_status]:
            raise UnverifiedUnitContractError(
                f"O asset '{self.asset_id}' está com verification_status="
                f"'{self.verification_status}', abaixo do mínimo '{minimum_status}'. "
                "Nenhuma estimativa pode ser emitida a partir dele."
            )


# -----------------------------------------------------------------------------
# Fatores de conversão biofísicos (cada um com a sua fonte)
# -----------------------------------------------------------------------------

# Eficiência máxima do uso da radiação para as braquiárias (Urochloa spp.) que
# dominam a pastagem cultivada brasileira. O valor central 0,50 gC/MJ é o adotado
# pela metodologia LAPIG/MapBiomas para pastagem no Brasil; o intervalo 0,40-0,65
# cobre a dispersão publicada entre cultivares e condições de fertilidade e é o
# que gera o intervalo de incerteza das estimativas de produtividade.
GRASS_LUE_MAX_GC_PER_MJ = 0.50
GRASS_LUE_MIN_GC_PER_MJ = 0.40
GRASS_LUE_UPPER_GC_PER_MJ = 0.65
GRASS_LUE_SOURCE = "LAPIG/MapBiomas - LUEmax para Urochloa spp. em pastagem cultivada no Brasil"

# Razão matéria seca / carbono. O IPCC (2006 GL, Vol.4, Cap.6) adota fração de
# carbono de 0,47 na biomassa de pastagem, o que corresponde a 1/0,47 = 2,128.
# O fator 2,7 usado na metodologia LAPIG embute, além da conversão C -> MS, a
# fração da produção primária bruta que se converte em biomassa aérea colhível.
# Os dois são mantidos nomeados e separados para que a conta fique auditável.
CARBON_TO_DRY_MATTER = 2.7
CARBON_TO_DRY_MATTER_SOURCE = "Metodologia LAPIG (C -> matéria seca aérea); IPCC 2006 GL Vol.4 Cap.6 (fração de C = 0,47)"

# 1 g/m² = 0,01 t/ha. Conversão puramente dimensional.
GRAMS_PER_M2_TO_TONS_PER_HA = 0.01


# -----------------------------------------------------------------------------
# Contratos dos assets
# -----------------------------------------------------------------------------

# Eficiência do uso do carbono (NPP/GPP). O produto histórico do Global Pasture
# Watch entrega GPP bruto em gC/m²; só uma fração vira produção primária líquida.
# O valor central 0,45 e a faixa 0,40-0,50 são os consolidados na literatura
# (Zhang et al. 2009, Global Biogeochem. Cycles; Collalti & Prentice 2019,
# Tree Physiology) e são o que separa GPP de matéria seca colhível.
CARBON_USE_EFFICIENCY = 0.45
CARBON_USE_EFFICIENCY_MIN = 0.40
CARBON_USE_EFFICIENCY_MAX = 0.50
CARBON_USE_EFFICIENCY_SOURCE = (
    "Zhang et al. (2009) e Collalti & Prentice (2019) - razão NPP/GPP (carbon use "
    "efficiency) de 0,40 a 0,50, com valor central 0,45"
)


# -----------------------------------------------------------------------------
# Contratos dos assets
# -----------------------------------------------------------------------------

# ATENÇÃO: os dois assets uGPP do Time2Graze armazenam o MESMO sinal físico em
# escalas DIFERENTES. Medido em 21/09/2026 sobre as 7 datas em comum no imóvel de
# referência, prod/cf = 0,0978 a 0,1057 (média ~0,10). Trocar um pelo outro sem
# trocar a escala erra a estimativa em 10x — foi o que aconteceu na implementação
# anterior, que usava escala 0,1 com o asset `cf`.

T2G_UGPP_CF_CONTRACT = AssetUnitContract(
    asset_id="projects/wri-lcl-time2graze/assets/ugpp_cf_10m_v1",
    band="ugpp",
    dtype="uint16",
    stored_scale=0.01,
    native_unit="MJ/m2/dia (radiação fotossinteticamente ativa absorvida, GPP sem o LUEmax)",
    temporal_support="instantaneous",
    nominal_resolution_m=10.0,
    observation_cadence_days=2.5,
    missing_data_policy=(
        "Pixel mascarado quando a cena não é válida (nuvem/sombra). A frequência de "
        "observação válida varia de ~13% (estação úmida) a ~92% (estação seca) das "
        "cenas do mês, e a acumulação mensal é uma extrapolação da média das "
        "observações válidas para os dias do mês."
    ),
    producer="WRI Land & Carbon Lab - Time2Graze",
    producer_version="ugpp_cf_10m_v1",
    documentation_url=None,
    verification_status="inferred",
    verified_on=date(2026, 9, 21),
    spatial_coverage=(
        "PARCIAL. Piloto restrito a poucos tiles MGRS. Em 21/09/2026, o imóvel de "
        "teste em Silvânia-GO (-48,75; -16,60) não tinha nenhuma cena, enquanto o de "
        "Córrego do Ouro-GO (-50,61; -16,36) tinha 308."
    ),
    temporal_coverage="2025-01-01 a 2026-07-30 (verificado em 21/09/2026)",
    known_bad_dates=("2025-07-03",),
    evidence=(
        "Banda única 'ugpp', uint16 (0-65535), EPSG:4326, crs_transform 8,3333e-05 grau (~9,26 m).",
        "Checagem física: em jan/2026 a média bruta sobre o imóvel de teste é 638. Com "
        "escala 0,01 isso dá 6,4 MJ/m²/dia de APAR, coerente com a radiação solar de "
        "~19 MJ/m²/dia em Goiás em janeiro (PAR = 0,45 x 19 = 8,6; fPAR ~0,8 -> ~6,9). "
        "Com escala 0,1 daria 63,8 MJ/m²/dia, 3,4x a radiação solar incidente total: impossível.",
        "Validação cruzada: acumulando 2025 inteiro no imóvel de teste, a escala 0,01 "
        "produz 14,5 t MS/ha/ano contra 21,1 t MS/ha/ano do MapBiomas no mesmo imóvel; "
        "a escala 0,1 produziria 144,9 t MS/ha/ano, ~7x o MapBiomas.",
        "Concordância com o asset `prod`: em julho/2026 os dois, com as suas escalas "
        "respectivas, dão 1,15 e 1,34 MJ/m²/dia de APAR (diferença de ~16%, não 10x).",
        "Outlier conhecido: em 2025-07-03 a média bruta é 9438, ~10x o normal do mês.",
    ),
    notes=(
        "Série histórica do piloto. Enquanto o produtor não publicar a documentação de "
        "unidade e escala, o status permanece 'inferred' e toda estimativa derivada "
        "carrega a flag 'asset_scale_inferred'.",
    ),
)

T2G_UGPP_PROD_CONTRACT = AssetUnitContract(
    asset_id="projects/wri-lcl-time2graze/assets/ugpp_prod_10m_v1",
    band="ugpp",
    dtype="int16",
    # Dez vezes a escala do `cf`: este asset armazena valores 10x menores.
    stored_scale=0.1,
    native_unit="MJ/m2/dia (radiação fotossinteticamente ativa absorvida, GPP sem o LUEmax)",
    temporal_support="instantaneous",
    nominal_resolution_m=10.0,
    observation_cadence_days=2.5,
    missing_data_policy=(
        "Pixel mascarado quando a cena não é válida (nuvem/sombra). Mesma política do "
        "asset `cf`."
    ),
    producer="WRI Land & Carbon Lab - Time2Graze",
    producer_version="ugpp_prod_10m_v1",
    documentation_url=None,
    verification_status="inferred",
    verified_on=date(2026, 9, 21),
    spatial_coverage="PARCIAL, mesma cobertura de tiles do asset `cf`.",
    temporal_coverage="2026-06-28 a 2026-08-21 (verificado em 21/09/2026)",
    known_bad_dates=("2025-07-03",),
    evidence=(
        "Banda única 'ugpp', int16 (0-32767) - metade da faixa do `cf`, coerente com "
        "valores 10x menores.",
        "Razão medida contra o `cf` nas 7 datas em comum do imóvel de referência: "
        "0,0978 / 0,1027 / 0,1035 / 0,1057 (média ~0,10). A escala deste asset é, "
        "portanto, 10x a do `cf`.",
        "Checagem física: julho/2026, média bruta 13,45 x 0,1 = 1,34 MJ/m²/dia de APAR, "
        "compatível com o 1,15 obtido pelo `cf` no mesmo mês (estação seca).",
    ),
    notes=(
        "Fluxo de produção corrente: cobre as datas mais recentes, que o `cf` ainda não "
        "tem. É o asset preferido para o mês atual; o `cf` responde pelo histórico.",
    ),
)

# Os dois assets, na ordem de preferência para uma data recente.
T2G_UGPP_CONTRACTS = (T2G_UGPP_PROD_CONTRACT, T2G_UGPP_CF_CONTRACT)

# Alias mantido para compatibilidade: o histórico continua sendo o `cf`.
T2G_UGPP_CONTRACT = T2G_UGPP_CF_CONTRACT

GPW_UGPP_HISTORICAL_CONTRACT = AssetUnitContract(
    asset_id="projects/global-pasture-watch/assets/ggpp-30m/v1/ugpp_m",
    band="gc_m2",
    dtype="uint16",
    stored_scale=1.0,
    native_unit="gC/m2/ano (GPP bruto acumulado no ano)",
    temporal_support="annual",
    nominal_resolution_m=30.0,
    observation_cadence_days=None,
    missing_data_policy="Uma imagem por ano; pixels fora da área mapeada ficam mascarados.",
    producer="Global Pasture Watch",
    producer_version="ggpp-30m v1 / ugpp_m",
    documentation_url="https://github.com/wri/global-pasture-watch",
    verification_status="inferred",
    verified_on=date(2026, 9, 21),
    spatial_coverage="Global",
    temporal_coverage="2000 a 2024 (25 imagens anuais, uma por ano)",
    evidence=(
        "25 imagens, system:index '2000'..'2024', system:time_start em 1º de janeiro e "
        "time_end em 31 de dezembro: suporte ANUAL, apesar do sufixo '_m' no nome.",
        "nominalScale medido no GEE: 27,83 m (grade de ~30 m), crs_transform 2,5e-04 grau.",
        "Valores de 1.700 a 2.100 gC/m²/ano nos imóveis de referência, faixa plausível "
        "de GPP anual de pastagem tropical. Sem escala a aplicar (stored_scale = 1,0).",
        "Validação cruzada contra o MapBiomas em 14 pares imóvel-ano (2005 a 2024, dois "
        "imóveis): o fator empírico MapBiomas / (gC x 2,7 x 0,01) é 0,402 +/- 0,013. "
        "Com a eficiência do uso do carbono de 0,45 da literatura, a estimativa fica "
        "+12% acima do MapBiomas em média (máximo +20,6%); a faixa de CUE 0,40-0,50 "
        "contém o valor do MapBiomas.",
    ),
    notes=(
        "Este produto é GPP BRUTO, não matéria seca: exige a eficiência do uso do "
        "carbono (NPP/GPP) além da conversão carbono -> matéria seca. É a série "
        "histórica 2000-2024 pedida na issue #112.",
    ),
)

MAPBIOMAS_PASTURE_BIOMASS_CONTRACT = AssetUnitContract(
    asset_id=(
        "projects/mapbiomas-public/assets/brazil/lulc/collection10/"
        "mapbiomas_brazil_collection10_pasture_biomass_v2"
    ),
    band="biomass_{year}",
    dtype="float",
    stored_scale=1.0,
    native_unit="t MS/ha/ano",
    temporal_support="annual",
    nominal_resolution_m=30.0,
    observation_cadence_days=None,
    missing_data_policy="Pixel sem pastagem mapeada no ano fica mascarado.",
    producer="MapBiomas Brasil",
    producer_version="Coleção 10 / pasture_biomass_v2",
    documentation_url="https://brasil.mapbiomas.org/produtos/",
    verification_status="documented",
    verified_on=date(2026, 9, 21),
    spatial_coverage="Brasil",
    temporal_coverage="2000 a 2024 (bandas biomass_2000..biomass_2024)",
    evidence=(
        "Valores de pixel entre 16 e 26 no imóvel de teste, consistentes com "
        "t MS/ha/ano de pastagem cultivada. Nenhuma escala a aplicar.",
        "A banda deve ser selecionada pelo NOME ('biomass_2024'); selecionar por "
        "índice ('select(year - 2000)') só funciona enquanto a primeira banda for "
        "biomass_2000.",
    ),
    notes=(
        "Produtividade ANUAL. Nunca deve ser apresentada como estimativa mensal atual "
        "nem como biomassa em pé.",
    ),
)

GPW_GRASSLAND_CONTRACT = AssetUnitContract(
    asset_id="projects/global-pasture-watch/assets/ggc-30m/v1-1/grassland_c",
    band="grassland_c",
    dtype="uint8",
    stored_scale=1.0,
    native_unit="classe (1 = pastagem natural/cultivada)",
    temporal_support="annual",
    nominal_resolution_m=30.0,
    observation_cadence_days=None,
    missing_data_policy="Sem classe atribuída fora da área mapeada.",
    producer="Global Pasture Watch",
    producer_version="ggc-30m v1-1",
    documentation_url="https://github.com/wri/global-pasture-watch",
    verification_status="documented",
    verified_on=date(2026, 9, 21),
    spatial_coverage="Global",
    temporal_coverage="Série anual",
    evidence=("nominalScale medido no GEE: 27,83 m (grade de ~30 m).",),
    notes=(
        "Usado como máscara, este produto define a resolução EFETIVA da análise em "
        "30 m mesmo quando o dado de origem é de 10 m.",
    ),
)

ASSET_CONTRACTS: Dict[str, AssetUnitContract] = {
    contract.asset_id: contract
    for contract in (
        T2G_UGPP_CF_CONTRACT,
        T2G_UGPP_PROD_CONTRACT,
        GPW_UGPP_HISTORICAL_CONTRACT,
        MAPBIOMAS_PASTURE_BIOMASS_CONTRACT,
        GPW_GRASSLAND_CONTRACT,
    )
}


def get_contract(asset_id: str) -> AssetUnitContract:
    """
    Recupera o contrato de unidade de um asset.

    Args:
        asset_id (str): Identificador do asset no Earth Engine.

    Returns:
        AssetUnitContract: Contrato registrado.

    Raises:
        UnverifiedUnitContractError: Se o asset não tiver contrato registrado.
    """
    contract = ASSET_CONTRACTS.get(asset_id)
    if contract is None:
        raise UnverifiedUnitContractError(
            f"Asset '{asset_id}' não tem contrato de unidade registrado em "
            "biomass_validation.ASSET_CONTRACTS. Nenhum fator de conversão pode ser "
            "aplicado sem contrato."
        )
    return contract


# -----------------------------------------------------------------------------
# Envelopes agronômicos
# -----------------------------------------------------------------------------

# Faixas plausíveis por hectare para pastagem tropical brasileira. O limite
# superior de cada envelope é o que impede um erro de escala de 10x voltar a
# circular: 26 t MS/ha em um único mês é mais do que um pasto produz em um ano.
AGRONOMIC_ENVELOPES: Dict[str, Tuple[float, float]] = {
    "monthly_dry_matter_productivity": (0.0, 6.0),
    "annual_dry_matter_productivity": (0.0, 45.0),
    "standing_dry_matter_biomass": (0.0, 15.0),
    "available_forage": (0.0, 12.0),
}

AGRONOMIC_ENVELOPES_SOURCE = (
    "Faixas de produtividade de Urochloa/Megathyrsus em condições brasileiras "
    "(Embrapa Gado de Corte; MapBiomas pasture_biomass). O teto mensal de 6 t MS/ha "
    "corresponde a um pasto irrigado e adubado no pico das águas."
)


def assert_within_envelope(metric_type: str, value_per_ha: Optional[float]) -> List[str]:
    """
    Verifica se o valor por hectare cabe no envelope agronômico da métrica.

    Args:
        metric_type (str): Métrica avaliada.
        value_per_ha (float, optional): Valor por hectare; None é aceito (sem estimativa).

    Returns:
        List[str]: Flags de qualidade (vazia quando o valor está confortavelmente dentro).

    Raises:
        ImplausibleEstimateError: Se o valor estourar o envelope — sintoma clássico
            de erro de escala ou de fator de conversão.
    """
    if value_per_ha is None:
        return []

    low, high = AGRONOMIC_ENVELOPES[metric_type]

    if value_per_ha < low or value_per_ha > high:
        raise ImplausibleEstimateError(
            f"{metric_type} = {value_per_ha:.2f} por hectare está fora do envelope "
            f"agronômico [{low:g}, {high:g}]. Isso indica erro de escala do asset ou de "
            f"fator de conversão, não uma pastagem excepcional. {AGRONOMIC_ENVELOPES_SOURCE}"
        )

    if value_per_ha > high * 0.85:
        return ["value_near_upper_envelope"]
    return []


def assert_annualizable(
    metric_type: str,
    temporal_support: str,
    period_days: int,
    minimum_days: int = 350,
) -> None:
    """
    Guarda que libera o cálculo de capacidade de suporte anual.

    A demanda animal é expressa em t MS/UA/ANO. Dividir uma produtividade mensal por
    esse denominador subestima a capacidade em cerca de 12x, que é exatamente o erro
    que esta função existe para impedir.

    Args:
        metric_type (str): Métrica base.
        temporal_support (str): Suporte temporal da métrica base.
        period_days (int): Duração do período coberto, em dias.
        minimum_days (int): Duração mínima aceita como base anual.

    Raises:
        IncompatibleTemporalSupportError: Se a base não for anual nem cobrir o ano.
    """
    if temporal_support != "annual":
        raise IncompatibleTemporalSupportError(
            f"Capacidade de suporte anual exige métrica com suporte temporal anual; "
            f"recebido '{temporal_support}' ({metric_type}). Uma produtividade mensal "
            "precisa ser anualizada por uma série de 12 meses antes de virar UA/ano."
        )

    if period_days < minimum_days:
        raise IncompatibleTemporalSupportError(
            f"A métrica declara suporte anual mas cobre apenas {period_days} dias "
            f"(mínimo {minimum_days}). Não há base para converter em UA/ano."
        )


def assert_is_stock_metric(metric_type: str) -> None:
    """
    Garante que a métrica represente um estoque, e não um fluxo de produção.

    Forragem disponível só pode ser derivada de biomassa EM PÉ. Descontar resíduo
    mínimo de uma produtividade mensal mistura fluxo com estoque.

    Args:
        metric_type (str): Métrica avaliada.

    Raises:
        IncompatibleTemporalSupportError: Se a métrica for de produtividade.
    """
    if metric_type in ("monthly_dry_matter_productivity", "annual_dry_matter_productivity"):
        raise IncompatibleTemporalSupportError(
            f"'{metric_type}' é produtividade (fluxo), não biomassa em pé (estoque). "
            "Forragem disponível só pode ser calculada sobre "
            "'standing_dry_matter_biomass'."
        )


def observation_quality_flags(
    valid_observation_fraction: Optional[float],
    low_threshold: float = 0.30,
    moderate_threshold: float = 0.60,
) -> List[str]:
    """
    Traduz a fração de observações válidas em flags de qualidade.

    Args:
        valid_observation_fraction (float, optional): Fração entre 0 e 1.
        low_threshold (float): Abaixo disso, cobertura considerada baixa.
        moderate_threshold (float): Abaixo disso, cobertura considerada moderada.

    Returns:
        List[str]: Flags aplicáveis.
    """
    if valid_observation_fraction is None:
        return ["valid_observation_fraction_unknown"]
    if valid_observation_fraction < low_threshold:
        return ["cloud_coverage_high", "low_valid_observations"]
    if valid_observation_fraction < moderate_threshold:
        return ["cloud_coverage_moderate"]
    return []


def mask_quality_flags(disagreement_fraction: Optional[float]) -> List[str]:
    """
    Traduz a divergência entre classificadores de pastagem em flags de qualidade.

    Args:
        disagreement_fraction (float, optional): Fração de pixels divergentes (0-1).

    Returns:
        List[str]: Flags aplicáveis.
    """
    if disagreement_fraction is None:
        return []
    if disagreement_fraction >= 0.20:
        return ["pasture_mask_disagreement_high"]
    if disagreement_fraction >= 0.05:
        return ["pasture_mask_disagreement_low"]
    return []


def contract_quality_flags(contract: AssetUnitContract) -> List[str]:
    """
    Flags derivadas do estado de verificação do contrato do asset.

    Args:
        contract (AssetUnitContract): Contrato usado na estimativa.

    Returns:
        List[str]: Flags aplicáveis.
    """
    if contract.verification_status == "inferred":
        return ["asset_scale_inferred"]
    if contract.verification_status == "unverified":
        return ["asset_unit_unverified"]
    return []


# -----------------------------------------------------------------------------
# Reprodutibilidade
# -----------------------------------------------------------------------------

def geometry_signature(coords: Any) -> str:
    """
    Assinatura estável da geometria, para uso em chave de cache.

    Args:
        coords: Estrutura de coordenadas (GeoJSON MultiPolygon aninhado).

    Returns:
        str: Hash sha256 truncado em 16 caracteres.
    """
    payload = json.dumps(coords, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_cache_key(
    metric_type: str,
    coords: Any,
    period_start: date,
    period_end: date,
    model_version: str,
    conversion_factors: Dict[str, float],
    mask_signature: str,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Monta a chave de cache de uma estimativa.

    Geometria, versão do modelo, fatores de conversão e máscara fazem parte da chave:
    mudar um fator invalida o cache em vez de devolver o número antigo.

    Args:
        metric_type (str): Métrica estimada.
        coords: Coordenadas da feição.
        period_start (date): Início do período.
        period_end (date): Fim do período.
        model_version (str): Versão do pipeline.
        conversion_factors (Dict[str, float]): Fatores aplicados.
        mask_signature (str): Assinatura da máscara (fonte + ano + resolução).
        extra (Dict[str, Any], optional): Componentes adicionais da chave.

    Returns:
        str: Chave determinística.
    """
    payload = {
        "metric_type": metric_type,
        "geometry": geometry_signature(coords),
        "period": [period_start.isoformat(), period_end.isoformat()],
        "model_version": model_version,
        "conversion_factors": {key: conversion_factors[key] for key in sorted(conversion_factors)},
        "mask": mask_signature,
        "extra": extra or {},
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return f"{metric_type}:{digest}"


@dataclass
class ValidationReport:
    """Resultado agregado das validações aplicadas a uma estimativa."""
    quality_flags: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    def merge(self, flags: List[str], limitation: Optional[str] = None) -> "ValidationReport":
        """Acumula flags sem duplicar e registra uma limitação opcional."""
        for flag in flags:
            if flag not in self.quality_flags:
                self.quality_flags.append(flag)
        if limitation and limitation not in self.limitations:
            self.limitations.append(limitation)
        return self
