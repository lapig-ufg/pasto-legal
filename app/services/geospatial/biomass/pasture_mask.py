"""Máscara de pastagem com metadados explícitos.

A máscara define a resolução EFETIVA de qualquer estimativa de biomassa: um
produto de 10 m recortado por uma máscara de 30 m é, na prática, uma análise de
30 m, e a interface precisa dizer isso.

Três estratégias:
  * "official"   - produto oficial recente (Global Pasture Watch, 30 m);
  * "on_the_fly" - classificador treinado sob demanda (Satellite Embedding, 10 m);
  * "hybrid"     - os dois, expondo a fração de divergência em vez de escondê-la.
"""

import datetime

from dataclasses import dataclass
from typing import Optional

import ee

from agno.utils.log import log_warning

from app.schemas.biomass_schemas import PastureMaskMetadata
from app.services.geospatial.biomass.biomass_validation import (
    GPW_GRASSLAND_CONTRACT,
    mask_quality_flags,
)


_GPW_ASSET = GPW_GRASSLAND_CONTRACT.asset_id

_GPW_FIRST_YEAR = 2000

# Probabilidade abaixo da qual o pixel do classificador on-the-fly é considerado
# incerto. O RandomForest do projeto devolve classe binária, então a incerteza é
# medida pela votação média das árvores quando disponível.
_UNCERTAIN_PROBABILITY_BAND = "pasto_probability"

MASK_MODEL_VERSION = "pasture-mask-v1"


@dataclass
class PastureMask:
    """
    Máscara de pastagem pronta para uso mais os metadados que a descrevem.

    Attributes:
        image (ee.Image): Imagem binária (1 = pastagem) para `updateMask`.
        metadata (PastureMaskMetadata): Fonte, ano, resolução e frações.
        quality_flags (list): Flags derivadas da divergência entre classificadores.
    """
    image: ee.Image
    metadata: PastureMaskMetadata
    quality_flags: list

    def signature(self) -> str:
        """Assinatura curta da máscara, usada como componente de chave de cache."""
        return (
            f"{self.metadata.source}|{self.metadata.source_version}|"
            f"{self.metadata.reference_year}|{self.metadata.resolution_m:g}|"
            f"{self.metadata.strategy}"
        )


def _latest_gpw_year(roi: ee.Geometry, requested_year: Optional[int]) -> int:
    """
    Ano mais recente do Global Pasture Watch disponível para a região.

    Args:
        roi (ee.Geometry): Região de interesse.
        requested_year (int, optional): Teto de ano pedido; None usa o ano corrente.

    Returns:
        int: Ano efetivamente disponível.

    Raises:
        ValueError: Se não houver nenhum ano mapeado para a região.
    """
    ceiling = requested_year or datetime.date.today().year

    collection = (
        ee.ImageCollection(_GPW_ASSET)
        .filterBounds(roi)
        .filterDate(f"{_GPW_FIRST_YEAR}-01-01", f"{ceiling + 1}-01-01")
        .sort("system:time_start", False)
    )

    timestamps = collection.limit(1).aggregate_array("system:time_start").getInfo()
    if not timestamps:
        raise ValueError(
            "Não há mapeamento de pastagem do Global Pasture Watch para esta região."
        )

    return datetime.datetime.fromtimestamp(
        timestamps[0] / 1000, tz=datetime.timezone.utc
    ).year


def _official_mask(roi: ee.Geometry, reference_year: Optional[int]) -> tuple:
    """
    Máscara oficial (Global Pasture Watch), com o ano efetivamente usado.

    Args:
        roi (ee.Geometry): Região de interesse.
        reference_year (int, optional): Ano desejado; cai para o mais recente disponível.

    Returns:
        tuple[ee.Image, int]: (máscara binária, ano de referência usado).
    """
    year = _latest_gpw_year(roi=roi, requested_year=reference_year)

    image = (
        ee.ImageCollection(_GPW_ASSET)
        .filterBounds(roi)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .first()
    )

    return image.gte(1).rename("pasture_mask"), year


def _on_the_fly_mask(roi: ee.Geometry, pred_year: int, train_year: int) -> ee.Image:
    """
    Máscara classificada sob demanda com Satellite Embedding + RandomForest.

    Reaproveita a amostragem e os hiperparâmetros de
    `pasture_classification`, para que a máscara e o mapa de classificação
    entregues ao usuário sejam o mesmo classificador.

    Args:
        roi (ee.Geometry): Região de interesse.
        pred_year (int): Ano alvo da predição.
        train_year (int): Ano de treino (rótulos MapBiomas + embedding).

    Returns:
        ee.Image: Imagem binária (1 = pastagem) na grade de 10 m do embedding.
    """
    from app.services.geospatial.pasture_classification import (
        _RF_TREES,
        _embedding,
        _samples,
    )

    samples, band_names = _samples(roi=roi, train_year=train_year)
    classifier = ee.Classifier.smileRandomForest(_RF_TREES).train(samples, "pasto", band_names)

    return (
        _embedding(roi=roi, year=pred_year)
        .classify(classifier)
        .rename("pasture_mask")
    )


def _area_ha(image: ee.Image, roi: ee.Geometry, scale: float) -> Optional[float]:
    """
    Área em hectares dos pixels válidos e não nulos de uma imagem binária.

    A conta usa `ee.Image.pixelArea()`, nunca um multiplicador fixo por resolução.

    Args:
        image (ee.Image): Imagem binária (1 = dentro da classe).
        roi (ee.Geometry): Região de interesse.
        scale (float): Escala de redução, em metros.

    Returns:
        float | None: Área em hectares, ou None quando não há pixel válido.
    """
    hectares = ee.Image.pixelArea().divide(10_000).updateMask(image)

    result = hectares.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=roi,
        scale=scale,
        maxPixels=1e13,
    ).getInfo()

    value = result.get("area")
    return None if value is None else float(value)


def build_pasture_mask(
    roi: ee.Geometry,
    reference_year: Optional[int] = None,
    strategy: str = "official",
    pred_year: Optional[int] = None,
    train_year: Optional[int] = None,
) -> PastureMask:
    """
    Constrói a máscara de pastagem com todos os metadados que a descrevem.

    Args:
        roi (ee.Geometry): Região de interesse (polígono do imóvel).
        reference_year (int, optional): Ano desejado da máscara oficial.
        strategy (str): "official", "on_the_fly" ou "hybrid".
        pred_year (int, optional): Ano alvo do classificador on-the-fly.
        train_year (int, optional): Ano de treino do classificador on-the-fly.

    Returns:
        PastureMask: Máscara + metadados (fonte, ano, resolução, frações, divergência).

    Raises:
        ValueError: Se a estratégia for desconhecida ou não houver máscara disponível.
    """
    if strategy not in ("official", "on_the_fly", "hybrid"):
        raise ValueError(f"Estratégia de máscara desconhecida: '{strategy}'.")

    property_area_ha = float(roi.area(1).getInfo()) / 10_000

    if strategy == "official":
        mask_image, used_year = _official_mask(roi=roi, reference_year=reference_year)
        resolution = GPW_GRASSLAND_CONTRACT.nominal_resolution_m
        pasture_area = _area_ha(mask_image.selfMask(), roi, resolution)

        metadata = PastureMaskMetadata(
            source=GPW_GRASSLAND_CONTRACT.producer,
            source_version=GPW_GRASSLAND_CONTRACT.producer_version,
            reference_year=used_year,
            resolution_m=resolution,
            pasture_area_ha=pasture_area,
            property_area_ha=property_area_ha,
            pasture_fraction=None if pasture_area is None else pasture_area / property_area_ha,
            strategy="official",
        )
        return PastureMask(image=mask_image, metadata=metadata, quality_flags=[])

    from app.services.geospatial.pasture_classification import _SCALE, _latest_mapbiomas_year

    train = train_year or _latest_mapbiomas_year()
    pred = pred_year or (train + 1)

    classified = _on_the_fly_mask(roi=roi, pred_year=pred, train_year=train)
    classified_area = _area_ha(classified.selfMask(), roi, _SCALE)

    if strategy == "on_the_fly":
        metadata = PastureMaskMetadata(
            source="Satellite Embedding V1 + RandomForest (on-the-fly)",
            source_version="GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL",
            reference_year=pred,
            resolution_m=float(_SCALE),
            classifier_version=f"{MASK_MODEL_VERSION}-rf-train{train}",
            pasture_area_ha=classified_area,
            property_area_ha=property_area_ha,
            pasture_fraction=None if classified_area is None else classified_area / property_area_ha,
            strategy="on_the_fly",
        )
        return PastureMask(image=classified, metadata=metadata, quality_flags=[])

    official, used_year = _official_mask(roi=roi, reference_year=reference_year)

    # A concordância é avaliada na grade mais grossa (30 m), que é a resolução
    # efetiva do par: comparar a 10 m daria uma divergência artificial de borda.
    effective_resolution = GPW_GRASSLAND_CONTRACT.nominal_resolution_m
    disagreement = classified.neq(official).rename("disagreement")

    disagreement_area = _area_ha(disagreement.selfMask(), roi, effective_resolution)
    disagreement_fraction = (
        None if disagreement_area is None else disagreement_area / property_area_ha
    )

    # União: a divergência é reportada, não resolvida silenciosamente em favor de
    # um dos classificadores.
    union = official.Or(classified).rename("pasture_mask")
    union_area = _area_ha(union.selfMask(), roi, effective_resolution)

    flags = mask_quality_flags(disagreement_fraction)
    if disagreement_fraction is not None and disagreement_fraction >= 0.20:
        log_warning(
            f"build_pasture_mask: divergência alta entre Global Pasture Watch {used_year} "
            f"e o classificador on-the-fly {pred}: {disagreement_fraction:.1%} da área."
        )

    metadata = PastureMaskMetadata(
        source=f"{GPW_GRASSLAND_CONTRACT.producer} + Satellite Embedding V1 (on-the-fly)",
        source_version=f"{GPW_GRASSLAND_CONTRACT.producer_version} / embedding {pred}",
        reference_year=used_year,
        resolution_m=effective_resolution,
        classifier_version=f"{MASK_MODEL_VERSION}-rf-train{train}",
        pasture_area_ha=union_area,
        property_area_ha=property_area_ha,
        pasture_fraction=None if union_area is None else union_area / property_area_ha,
        disagreement_fraction=disagreement_fraction,
        strategy="hybrid",
    )

    return PastureMask(image=union, metadata=metadata, quality_flags=flags)
