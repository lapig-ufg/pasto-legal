"""MapBiomas assets, class names and year helpers.

Every pasture layer (classification, age, vigor, LULC) uses a different
MapBiomas asset, with different band layouts and base years. This module keeps
those details in one place so the analysis modules do not duplicate asset IDs
or year-clamping logic.
"""

from typing import Dict

import ee


# 10m Collection 3 integration — used as the label source for the on-the-fly
# classification and as its static fallback.
CLASSIFICATION_ASSET = (
    "projects/mapbiomas-public/assets/brazil/lulc_10m/collection3/"
    "mapbiomas_10m_collection3_integration_v1"
)

# 30m Collection 10 assets.
AGE_ASSET = (
    "projects/mapbiomas-public/assets/brazil/lulc/collection10/"
    "mapbiomas_brazil_collection10_pasture_age_v2"
)
VIGOR_ASSET = (
    "projects/mapbiomas-public/assets/brazil/lulc/collection10/"
    "mapbiomas_brazil_collection10_pasture_vigor_v3"
)
LULC_ASSET = (
    "projects/mapbiomas-public/assets/brazil/lulc/collection10/"
    "mapbiomas_brazil_collection10_integration_v2"
)

# Band 0 of the age/LULC assets is classification_1985; the vigor asset starts
# at 2000.
AGE_ASSET_BASE_YEAR = 1985
LULC_ASSET_BASE_YEAR = 1985
VIGOR_ASSET_BASE_YEAR = 2000

PASTURE_CLASS = 15

# 30-40 = age measured precisely in that interval. ≥40 = pixel hit the asset's
# encoding ceiling (already mature at the start of the series, real age unknown)
# or reached 40 through the projected +1 year — both mean "at least ~40 years,
# without precision beyond that". Kept separate from the measured 30-40 class.
AGE_CLASSES: Dict[int, str] = {
    1: "1-10",
    2: "10-20",
    3: "20-30",
    4: "30-40",
    5: "≥40 (idade real indeterminada)",
}

VIGOR_CLASSES: Dict[int, str] = {
    1: "Baixo: pastagens com baixo vigor vegetativo e indícios de degradação severa, potencialmente biológica.",
    2: "Médio: pastagens com médio vigor vegativo e indícios de degração moderada.",
    3: "Alto: pastagens com alto vigor vegetativo.",
}

LULC_CLASSES: Dict[int, str] = {
    3: "Formação Florestal",
    4: "Formação Savânica",
    5: "Mangue",
    6: "Floresta Alagável",
    9: "Silvicultura",
    11: "Campo Alagado e Área Pantanosa",
    12: "Formação Campestre",
    15: "Pastagem",
    19: "Lavoura Temporária",
    20: "Cana",
    21: "Mosaico de Usos",
    23: "Praia, Duna e Areal",
    24: "Área Urbanizada",
    25: "Outras Áreas não Vegetadas",
    26: "Corpo D'água",
    27: "Não observado",
    29: "Afloramento Rochoso",
    30: "Mineração",
    31: "Aquicultura",
    32: "Apicum",
    33: "Rio, Lago e Oceano",
    35: "Dendê",
    36: "Lavoura Perene",
    39: "Soja",
    40: "Arroz",
    41: "Outras Lavouras Temporárias",
    46: "Café",
    47: "Citrus",
    48: "Outras Lavouras Perenes",
    49: "Restinga Arbórea",
    50: "Restinga Herbácea",
    62: "Algodão",
    75: "Usina Fotovoltaica (beta)",
}


def latest_asset_year(asset_id: str, base_year: int = 2000) -> int:
    """Latest year available in an asset whose bands are indexed by position.

    Band 0 is ``base_year``, band 1 is ``base_year + 1``, and so on. Used by the
    age, vigor and LULC assets.
    """
    band_count = ee.Image(asset_id).bandNames().size().getInfo()
    return base_year + band_count - 1


def latest_classification_year() -> int:
    """Most recent year with a ``classification_YYYY`` band in the 10m asset."""
    bands = ee.Image(CLASSIFICATION_ASSET).bandNames().getInfo()
    years = [
        int(band.replace("classification_", ""))
        for band in bands
        if band.startswith("classification_")
    ]
    return max(years)
