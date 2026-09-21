"""Biomassa em pé (t MS/ha) — modelo supervisionado separado da produtividade.

Produtividade e biomassa em pé são grandezas diferentes: a primeira é o fluxo de
produção acumulado num período, a segunda é o estoque de massa seca que está no
piquete agora. Um pasto pode ter alta produtividade e pouca massa em pé (pastejo
intenso), e o contrário também acontece (pasto diferido).

Por isso este módulo NÃO deriva biomassa em pé do GPP. Ele define:

  1. `build_feature_stack` - a pilha de covariáveis (óptico, radar, índices,
     clima, relevo, solo, máscara) calculada no Earth Engine;
  2. `extract_training_samples` - a extração dessas covariáveis nos pontos de
     campo, com a massa seca MEDIDA como alvo;
  3. `train_standing_biomass_model` - o treino OFFLINE, versionado, com validação
     espacial por fazenda e temporal por safra, e quantis P10/P50/P90;
  4. `estimate_standing_biomass` - a inferência on-the-fly sobre o imóvel.

Enquanto não houver um modelo calibrado registrado, a inferência levanta
`CalibratedModelUnavailableError`. Ela não inventa um número a partir de GPP.
"""

import datetime
import json

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import ee

from agno.utils.log import log_info, log_warning

from app.schemas.biomass_schemas import BiomassEstimate
from app.services.geospatial.biomass.biomass_validation import (
    BiomassValidationError,
    ValidationReport,
    assert_within_envelope,
    mask_quality_flags,
    observation_quality_flags,
)
from app.services.geospatial.biomass.pasture_mask import PastureMask, build_pasture_mask


class CalibratedModelUnavailableError(BiomassValidationError):
    """Não há modelo de biomassa em pé calibrado e versionado para uso."""


MODEL_REGISTRY_DIR = Path("data/models/standing_biomass")

_S2_ASSET = "COPERNICUS/S2_SR_HARMONIZED"
_S2_CLOUD_SCORE_ASSET = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"
_S1_ASSET = "COPERNICUS/S1_GRD"
_CHIRPS_ASSET = "UCSB-CHG/CHIRPS/DAILY"
_ERA5_ASSET = "ECMWF/ERA5_LAND/DAILY_AGGR"
_DEM_ASSET = "COPERNICUS/DEM/GLO30"
_SOIL_CLAY_ASSET = "projects/soilgrids-isric/clay_mean"
_SOIL_SAND_ASSET = "projects/soilgrids-isric/sand_mean"
_BIOME_ASSET = "projects/mapbiomas-workspace/AUXILIAR/biomas-2019-raster"

# Limiar do Cloud Score+ (cs_cdf): abaixo disso o pixel é descartado. O mesmo
# valor usado na série NDVI harmônica do projeto.
_CLOUD_SCORE_THRESHOLD = 0.60

# Janela de composição óptica. 30 dias equilibra cobertura de nuvem no período
# úmido e representatividade temporal da massa em pé.
_COMPOSITE_WINDOW_DAYS = 30

_S2_BANDS = ["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"]

_RAINFALL_WINDOWS_DAYS = (15, 30, 60, 90)

# Escala de inferência. 10 m é a grade do Sentinel-2; a resolução EFETIVA
# continua sendo a da máscara de pastagem.
_INFERENCE_SCALE_M = 10.0


@dataclass
class StandingBiomassModelManifest:
    """
    Manifesto de um modelo treinado — o que permite auditar e reproduzir a inferência.

    Attributes:
        model_version (str): Identificador versionado, por exemplo "standing-biomass-v1".
        backend (str): Biblioteca usada no treino ("lightgbm", "catboost", "sklearn-gbr").
        features (List[str]): Nomes das covariáveis, na ordem esperada pelo modelo.
        quantiles (Dict[str, str]): Mapa quantil -> arquivo do modelo correspondente.
        target_unit (str): Unidade do alvo medido em campo.
        trained_on (str): Data do treino (ISO).
        n_samples (int): Número de amostras de campo usadas.
        n_farms (int): Número de fazendas distintas.
        spatial_cv (Dict): Métricas da validação espacial por fazenda.
        temporal_cv (Dict): Métricas da validação temporal por safra.
        strata_metrics (Dict): Métricas por estrato (bioma, estação, espécie).
        notes (List[str]): Observações técnicas.
    """
    model_version: str
    backend: str
    features: List[str]
    quantiles: Dict[str, str]
    target_unit: str = "t_DM_ha"
    trained_on: str = ""
    n_samples: int = 0
    n_farms: int = 0
    spatial_cv: Dict[str, Any] = field(default_factory=dict)
    temporal_cv: Dict[str, Any] = field(default_factory=dict)
    strata_metrics: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_path(cls, path: Path) -> "StandingBiomassModelManifest":
        """Lê um manifesto do disco."""
        payload = json.loads(path.read_text(encoding="utf-8"))
        known = {key: payload[key] for key in payload if key in cls.__dataclass_fields__}
        return cls(**known)

    def to_path(self, path: Path) -> None:
        """Grava o manifesto no disco."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=2, ensure_ascii=False), encoding="utf-8")


def available_models(registry_dir: Path = MODEL_REGISTRY_DIR) -> List[str]:
    """
    Versões de modelo de biomassa em pé registradas.

    Args:
        registry_dir (Path): Diretório do registro de modelos.

    Returns:
        List[str]: Versões disponíveis, em ordem alfabética.
    """
    if not registry_dir.exists():
        return []
    return sorted(path.stem for path in registry_dir.glob("*.json"))


def load_manifest(
    model_version: Optional[str] = None,
    registry_dir: Path = MODEL_REGISTRY_DIR,
) -> StandingBiomassModelManifest:
    """
    Carrega o manifesto de um modelo calibrado.

    Args:
        model_version (str, optional): Versão desejada; None usa a mais recente.
        registry_dir (Path): Diretório do registro de modelos.

    Returns:
        StandingBiomassModelManifest: Manifesto carregado.

    Raises:
        CalibratedModelUnavailableError: Se não houver modelo registrado.
    """
    versions = available_models(registry_dir)

    if not versions:
        raise CalibratedModelUnavailableError(
            "Não há modelo de biomassa em pé calibrado e versionado em "
            f"'{registry_dir}'. Biomassa em pé exige um modelo treinado com massa "
            "seca MEDIDA em campo (kg MS/ha ou t MS/ha) — ela não pode ser derivada "
            "de GPP nem da produtividade mensal. Use "
            "`train_standing_biomass_model` com dados de campo antes de habilitar "
            "esta métrica."
        )

    target = model_version or versions[-1]
    if target not in versions:
        raise CalibratedModelUnavailableError(
            f"Modelo '{target}' não registrado. Disponíveis: {', '.join(versions)}."
        )

    return StandingBiomassModelManifest.from_path(registry_dir / f"{target}.json")


# -----------------------------------------------------------------------------
# Covariáveis
# -----------------------------------------------------------------------------

def _s2_composite(roi: ee.Geometry, target_date: datetime.date, window_days: int) -> ee.Image:
    """
    Composição Sentinel-2 mediana da janela, com filtragem por Cloud Score+.

    Args:
        roi (ee.Geometry): Região de interesse.
        target_date (datetime.date): Data alvo (fim da janela).
        window_days (int): Tamanho da janela de composição, em dias.

    Returns:
        ee.Image: Composição refletância (0-1) com as bandas de `_S2_BANDS`.
    """
    start = (target_date - datetime.timedelta(days=window_days)).isoformat()
    end = target_date.isoformat()

    collection = (
        ee.ImageCollection(_S2_ASSET)
        .filterBounds(roi)
        .filterDate(start, end)
        .linkCollection(ee.ImageCollection(_S2_CLOUD_SCORE_ASSET), ["cs_cdf"])
    )

    def _mask_clouds(image: ee.Image) -> ee.Image:
        return image.updateMask(image.select("cs_cdf").gte(_CLOUD_SCORE_THRESHOLD))

    return (
        collection.map(_mask_clouds)
        .select(_S2_BANDS)
        .median()
        .divide(10_000)
    )


def _spectral_indices(composite: ee.Image) -> ee.Image:
    """
    Índices espectrais sensíveis a massa verde, água foliar e clorofila do red-edge.

    Args:
        composite (ee.Image): Composição Sentinel-2 em refletância.

    Returns:
        ee.Image: Bandas NDVI, EVI2, NDRE, LSWI e NDRE2.
    """
    ndvi = composite.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndre = composite.normalizedDifference(["B8", "B5"]).rename("NDRE")
    ndre2 = composite.normalizedDifference(["B8", "B6"]).rename("NDRE2")
    lswi = composite.normalizedDifference(["B8", "B11"]).rename("LSWI")

    evi2 = composite.expression(
        "2.5 * (nir - red) / (nir + 2.4 * red + 1.0)",
        {"nir": composite.select("B8"), "red": composite.select("B4")},
    ).rename("EVI2")

    return ndvi.addBands([ndre, ndre2, lswi, evi2])


def _s1_features(roi: ee.Geometry, target_date: datetime.date, window_days: int) -> ee.Image:
    """
    Estatísticas Sentinel-1 (VV, VH e razão) na janela — sensíveis à estrutura do dossel.

    Args:
        roi (ee.Geometry): Região de interesse.
        target_date (datetime.date): Data alvo (fim da janela).
        window_days (int): Tamanho da janela, em dias.

    Returns:
        ee.Image: Médias e desvios de VV, VH e VV/VH.
    """
    start = (target_date - datetime.timedelta(days=window_days)).isoformat()
    end = target_date.isoformat()

    collection = (
        ee.ImageCollection(_S1_ASSET)
        .filterBounds(roi)
        .filterDate(start, end)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .select(["VV", "VH"])
    )

    def _add_ratio(image: ee.Image) -> ee.Image:
        return image.addBands(image.select("VV").subtract(image.select("VH")).rename("VV_VH"))

    with_ratio = collection.map(_add_ratio)

    return (
        with_ratio.mean().rename(["VV_mean", "VH_mean", "VV_VH_mean"])
        .addBands(with_ratio.reduce(ee.Reducer.stdDev()).rename(["VV_std", "VH_std", "VV_VH_std"]))
    )


def _rainfall_features(roi: ee.Geometry, target_date: datetime.date) -> ee.Image:
    """
    Chuva acumulada em 15, 30, 60 e 90 dias antes da data alvo (CHIRPS).

    Args:
        roi (ee.Geometry): Região de interesse.
        target_date (datetime.date): Data alvo.

    Returns:
        ee.Image: Bandas rain_15d, rain_30d, rain_60d e rain_90d, em mm.
    """
    chirps = ee.ImageCollection(_CHIRPS_ASSET).filterBounds(roi)

    bands = []
    for window in _RAINFALL_WINDOWS_DAYS:
        start = (target_date - datetime.timedelta(days=window)).isoformat()
        bands.append(
            chirps.filterDate(start, target_date.isoformat())
            .sum()
            .rename(f"rain_{window}d")
        )

    return ee.Image.cat(bands)


def _climate_features(roi: ee.Geometry, target_date: datetime.date, window_days: int) -> ee.Image:
    """
    Temperatura, radiação e déficit hídrico médios na janela (ERA5-Land).

    Args:
        roi (ee.Geometry): Região de interesse.
        target_date (datetime.date): Data alvo.
        window_days (int): Tamanho da janela, em dias.

    Returns:
        ee.Image: Bandas temp_mean_c, radiation_mj_m2 e water_deficit_mm.
    """
    start = (target_date - datetime.timedelta(days=window_days)).isoformat()
    end = target_date.isoformat()

    era5 = (
        ee.ImageCollection(_ERA5_ASSET)
        .filterBounds(roi)
        .filterDate(start, end)
    )

    temperature = era5.select("temperature_2m").mean().subtract(273.15).rename("temp_mean_c")
    radiation = (
        era5.select("surface_solar_radiation_downwards_sum").mean()
        .divide(1e6)
        .rename("radiation_mj_m2")
    )

    # Déficit hídrico simplificado: evapotranspiração potencial menos precipitação
    # na mesma janela. Valores positivos indicam demanda não atendida.
    evaporation = era5.select("potential_evaporation_sum").mean().multiply(-1000)
    precipitation = era5.select("total_precipitation_sum").mean().multiply(1000)
    deficit = evaporation.subtract(precipitation).rename("water_deficit_mm")

    return temperature.addBands([radiation, deficit])


def _terrain_and_soil_features(roi: ee.Geometry) -> ee.Image:
    """
    Relevo (elevação, declividade), solo (argila, areia) e bioma.

    Args:
        roi (ee.Geometry): Região de interesse.

    Returns:
        ee.Image: Bandas elevation, slope, clay_0_30, sand_0_30 e biome.
    """
    dem_collection = ee.ImageCollection(_DEM_ASSET).filterBounds(roi)
    projection = dem_collection.first().projection()
    dem = dem_collection.select("DEM").mosaic().setDefaultProjection(projection)

    elevation = dem.rename("elevation")
    slope = ee.Terrain.slope(dem).rename("slope")

    clay = ee.Image(_SOIL_CLAY_ASSET).select(0).rename("clay_0_30")
    sand = ee.Image(_SOIL_SAND_ASSET).select(0).rename("sand_0_30")
    biome = ee.Image(_BIOME_ASSET).select(0).rename("biome")

    return elevation.addBands([slope, clay, sand, biome])


def build_feature_stack(
    roi: ee.Geometry,
    target_date: datetime.date,
    mask: PastureMask,
    window_days: int = _COMPOSITE_WINDOW_DAYS,
    annual_productivity_image: Optional[ee.Image] = None,
) -> ee.Image:
    """
    Pilha completa de covariáveis para o modelo de biomassa em pé.

    A mesma pilha é usada no treino (amostrada nos pontos de campo) e na
    inferência (sobre o imóvel), o que impede divergência entre as duas etapas.

    Args:
        roi (ee.Geometry): Região de interesse.
        target_date (datetime.date): Data alvo da estimativa.
        mask (PastureMask): Máscara de pastagem (entra como covariável e como recorte).
        window_days (int): Janela de composição óptica/radar, em dias.
        annual_productivity_image (ee.Image, optional): Histórico de produtividade
            anual, quando disponível, como covariável de sazonalidade/potencial.

    Returns:
        ee.Image: Imagem multibanda com todas as covariáveis, recortada no roi.
    """
    composite = _s2_composite(roi=roi, target_date=target_date, window_days=window_days)

    stack = (
        composite
        .addBands(_spectral_indices(composite))
        .addBands(_s1_features(roi=roi, target_date=target_date, window_days=window_days))
        .addBands(_rainfall_features(roi=roi, target_date=target_date))
        .addBands(_climate_features(roi=roi, target_date=target_date, window_days=window_days))
        .addBands(_terrain_and_soil_features(roi=roi))
        .addBands(mask.image.rename("pasture_mask"))
        .addBands(ee.Image.constant(target_date.timetuple().tm_yday).rename("day_of_year"))
    )

    if annual_productivity_image is not None:
        stack = stack.addBands(annual_productivity_image.rename("annual_productivity_t_ha"))

    return stack.clip(roi)


def feature_names(include_annual_productivity: bool = False) -> List[str]:
    """
    Nomes das covariáveis na ordem em que a pilha as produz.

    Args:
        include_annual_productivity (bool): Se a covariável de histórico entra na lista.

    Returns:
        List[str]: Nomes das bandas.
    """
    names = list(_S2_BANDS)
    names += ["NDVI", "NDRE", "NDRE2", "LSWI", "EVI2"]
    names += ["VV_mean", "VH_mean", "VV_VH_mean", "VV_std", "VH_std", "VV_VH_std"]
    names += [f"rain_{window}d" for window in _RAINFALL_WINDOWS_DAYS]
    names += ["temp_mean_c", "radiation_mj_m2", "water_deficit_mm"]
    names += ["elevation", "slope", "clay_0_30", "sand_0_30", "biome"]
    names += ["pasture_mask", "day_of_year"]

    if include_annual_productivity:
        names.append("annual_productivity_t_ha")

    return names


# -----------------------------------------------------------------------------
# Treino offline
# -----------------------------------------------------------------------------

def extract_training_samples(
    field_plots: ee.FeatureCollection,
    date_property: str = "sample_date",
    farm_property: str = "farm_id",
    target_property: str = "standing_dm_t_ha",
    window_days: int = _COMPOSITE_WINDOW_DAYS,
    scale: float = _INFERENCE_SCALE_M,
) -> List[Dict[str, Any]]:
    """
    Extrai as covariáveis nos pontos de campo, mantendo o alvo MEDIDO.

    Cada parcela é amostrada na sua própria data, com a janela terminando na data
    da coleta — amostrar todas as parcelas numa data comum vazaria informação
    temporal para o modelo.

    Args:
        field_plots (ee.FeatureCollection): Parcelas de campo com alvo e data.
        date_property (str): Propriedade com a data da coleta (ISO).
        farm_property (str): Propriedade com o identificador da fazenda.
        target_property (str): Propriedade com a massa seca medida, em t MS/ha.
        window_days (int): Janela de composição, em dias.
        scale (float): Escala de amostragem, em metros.

    Returns:
        List[Dict[str, Any]]: Linhas prontas para o treino (covariáveis + alvo +
        farm_id + data), com as parcelas sem covariável válida descartadas.
    """
    plots = field_plots.getInfo()["features"]
    rows: List[Dict[str, Any]] = []

    for plot in plots:
        properties = plot["properties"]
        sample_date = datetime.date.fromisoformat(properties[date_property])
        geometry = ee.Geometry(plot["geometry"])
        roi = geometry.buffer(scale * 3).bounds()

        mask = build_pasture_mask(roi=roi, strategy="official")
        stack = build_feature_stack(
            roi=roi, target_date=sample_date, mask=mask, window_days=window_days
        )

        sampled = stack.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=scale,
            maxPixels=1e9,
        ).getInfo()

        if any(value is None for value in sampled.values()):
            log_warning(
                f"extract_training_samples: parcela {properties.get(farm_property)} em "
                f"{sample_date} descartada por covariável faltante."
            )
            continue

        row = dict(sampled)
        row["target_standing_dm_t_ha"] = float(properties[target_property])
        row["farm_id"] = properties[farm_property]
        row["sample_date"] = sample_date.isoformat()
        rows.append(row)

    log_info(f"extract_training_samples: {len(rows)} de {len(plots)} parcelas aproveitadas.")
    return rows


def train_standing_biomass_model(
    samples: List[Dict[str, Any]],
    model_version: str,
    registry_dir: Path = MODEL_REGISTRY_DIR,
    quantiles: tuple = (0.10, 0.50, 0.90),
    stratify_by: Optional[str] = "biome",
) -> StandingBiomassModelManifest:
    """
    Treina offline os modelos quantílicos de biomassa em pé e registra a versão.

    O treino é deliberadamente offline: a inferência on-the-fly consome um artefato
    versionado, e nenhuma calibração acontece no caminho de resposta ao usuário.

    A validação é dupla e obrigatória:
      * espacial, agrupando por fazenda (`GroupKFold` por `farm_id`), para que
        parcelas vizinhas da mesma fazenda não apareçam em treino e teste;
      * temporal, separando por safra/ano da coleta.

    Args:
        samples (List[Dict[str, Any]]): Linhas de `extract_training_samples`.
        model_version (str): Identificador da versão, por exemplo "standing-biomass-v1".
        registry_dir (Path): Diretório do registro de modelos.
        quantiles (tuple): Quantis a treinar (P10/P50/P90 por padrão).
        stratify_by (str, optional): Covariável usada para reportar métricas por estrato.

    Returns:
        StandingBiomassModelManifest: Manifesto gravado no registro.

    Raises:
        ImportError: Se scikit-learn (grupo dev) não estiver instalado.
        ValueError: Se as amostras forem insuficientes para validação espacial.
    """
    try:
        import joblib
        import numpy as np
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.model_selection import GroupKFold
    except ImportError as error:
        raise ImportError(
            "O treino de biomassa em pé exige scikit-learn e joblib (grupo `dev` do "
            "pyproject). Instale com `uv sync --group dev`."
        ) from error

    if not samples:
        raise ValueError("Nenhuma amostra de campo informada.")

    farms = sorted({row["farm_id"] for row in samples})
    if len(farms) < 3:
        raise ValueError(
            f"A validação espacial exige pelo menos 3 fazendas distintas; foram "
            f"informadas {len(farms)}. Sem isso o modelo mede a própria fazenda, "
            "não a capacidade de generalizar."
        )

    features = [
        name for name in samples[0]
        if name not in ("target_standing_dm_t_ha", "farm_id", "sample_date")
    ]
    features.sort()

    matrix = np.array([[row[name] for name in features] for row in samples], dtype=float)
    target = np.array([row["target_standing_dm_t_ha"] for row in samples], dtype=float)
    groups = np.array([row["farm_id"] for row in samples])
    years = np.array([int(row["sample_date"][:4]) for row in samples])

    def _metrics(observed, predicted) -> Dict[str, float]:
        residual = predicted - observed
        return {
            "n": int(len(observed)),
            "rmse": float(np.sqrt(np.mean(residual ** 2))),
            "mae": float(np.mean(np.abs(residual))),
            "bias": float(np.mean(residual)),
            "r2": float(
                1 - np.sum(residual ** 2) / np.sum((observed - np.mean(observed)) ** 2)
            ) if len(observed) > 1 and np.std(observed) > 0 else float("nan"),
        }

    def _fit(train_index, quantile: float):
        model = GradientBoostingRegressor(
            loss="quantile", alpha=quantile, n_estimators=400,
            max_depth=4, learning_rate=0.05, subsample=0.8, random_state=42,
        )
        model.fit(matrix[train_index], target[train_index])
        return model

    # Validação espacial: cada fold retém fazendas inteiras.
    spatial_folds = GroupKFold(n_splits=min(5, len(farms)))
    spatial_observed, spatial_predicted = [], []
    for train_index, test_index in spatial_folds.split(matrix, target, groups):
        median_model = _fit(train_index, 0.50)
        spatial_observed.extend(target[test_index].tolist())
        spatial_predicted.extend(median_model.predict(matrix[test_index]).tolist())

    spatial_cv = _metrics(np.array(spatial_observed), np.array(spatial_predicted))
    spatial_cv["scheme"] = f"GroupKFold por farm_id ({len(farms)} fazendas)"

    # Validação temporal: treina no passado, testa na safra seguinte.
    temporal_observed, temporal_predicted = [], []
    for year in sorted(set(years))[1:]:
        train_index = np.where(years < year)[0]
        test_index = np.where(years == year)[0]
        if len(train_index) < 10 or len(test_index) == 0:
            continue
        median_model = _fit(train_index, 0.50)
        temporal_observed.extend(target[test_index].tolist())
        temporal_predicted.extend(median_model.predict(matrix[test_index]).tolist())

    temporal_cv = (
        _metrics(np.array(temporal_observed), np.array(temporal_predicted))
        if temporal_observed else {"n": 0, "note": "safras insuficientes para validação temporal"}
    )
    temporal_cv["scheme"] = "treino nas safras anteriores, teste na safra seguinte"

    strata_metrics: Dict[str, Any] = {}
    if stratify_by and stratify_by in features:
        column = features.index(stratify_by)
        predictions = np.array(spatial_predicted)
        observations = np.array(spatial_observed)
        # As predições espaciais saem na ordem dos folds; reordena pelo índice original.
        order = np.concatenate([
            test_index for _, test_index in spatial_folds.split(matrix, target, groups)
        ])
        for stratum in sorted(set(matrix[:, column].tolist())):
            selected = matrix[order, column] == stratum
            if selected.sum() >= 5:
                strata_metrics[str(stratum)] = _metrics(
                    observations[selected], predictions[selected]
                )

    registry_dir.mkdir(parents=True, exist_ok=True)
    all_index = np.arange(len(target))
    quantile_files: Dict[str, str] = {}

    for quantile in quantiles:
        model = _fit(all_index, quantile)
        filename = f"{model_version}_q{int(quantile * 100):02d}.joblib"
        joblib.dump(model, registry_dir / filename)
        quantile_files[f"p{int(quantile * 100):02d}"] = filename

    manifest = StandingBiomassModelManifest(
        model_version=model_version,
        backend="sklearn-gbr-quantile",
        features=features,
        quantiles=quantile_files,
        trained_on=datetime.date.today().isoformat(),
        n_samples=len(samples),
        n_farms=len(farms),
        spatial_cv=spatial_cv,
        temporal_cv=temporal_cv,
        strata_metrics=strata_metrics,
        notes=[
            "Alvo: massa seca em pé MEDIDA em campo (t MS/ha). O modelo nunca é "
            "treinado contra GPP ou produtividade estimada.",
            "Inferência on-the-fly; treino offline e versionado.",
        ],
    )
    manifest.to_path(registry_dir / f"{model_version}.json")

    log_info(
        f"train_standing_biomass_model: {model_version} treinado com {len(samples)} "
        f"amostras de {len(farms)} fazendas (RMSE espacial {spatial_cv['rmse']:.2f} t MS/ha)."
    )
    return manifest


# -----------------------------------------------------------------------------
# Inferência on-the-fly
# -----------------------------------------------------------------------------

def enforce_monotonic_quantiles(
    lower: Optional[float],
    median: Optional[float],
    upper: Optional[float],
) -> tuple:
    """
    Garante P10 <= P50 <= P90 na saída da inferência.

    Modelos quantílicos treinados de forma independente se cruzam em uma fração
    das amostras (aqui, ~10% dos casos nos testes sintéticos): o P90 pode sair
    abaixo do P50. Ordenar os três valores é a correção padrão e mantém o P50
    como estimativa central sempre que ele já estiver entre os extremos.

    Args:
        lower (float, optional): Predição do quantil 10.
        median (float, optional): Predição do quantil 50.
        upper (float, optional): Predição do quantil 90.

    Returns:
        tuple: (limite inferior, valor central, limite superior) em ordem crescente.
    """
    values = [value for value in (lower, median, upper) if value is not None]

    if len(values) < 3:
        return lower, median, upper

    ordered = sorted(values)
    return ordered[0], ordered[1], ordered[2]


def estimate_standing_biomass(
    roi: ee.Geometry,
    target_date: Optional[datetime.date] = None,
    mask: Optional[PastureMask] = None,
    model_version: Optional[str] = None,
    registry_dir: Path = MODEL_REGISTRY_DIR,
    window_days: int = _COMPOSITE_WINDOW_DAYS,
) -> BiomassEstimate:
    """
    Estima a biomassa em pé (t MS/ha) do imóvel com o modelo calibrado versionado.

    Args:
        roi (ee.Geometry): Região de interesse (polígono do imóvel).
        target_date (datetime.date, optional): Data alvo; None usa hoje.
        mask (PastureMask, optional): Máscara de pastagem; None constrói a híbrida.
        model_version (str, optional): Versão do modelo; None usa a mais recente.
        registry_dir (Path): Diretório do registro de modelos.
        window_days (int): Janela de composição, em dias.

    Returns:
        BiomassEstimate: Estimativa com P50 como valor central e P10/P90 como intervalo.

    Raises:
        CalibratedModelUnavailableError: Se não houver modelo calibrado registrado.
        ImplausibleEstimateError: Se o valor estourar o envelope agronômico.
    """
    import joblib
    import numpy as np

    manifest = load_manifest(model_version=model_version, registry_dir=registry_dir)

    reference_date = target_date or datetime.date.today()
    pasture_mask = mask or build_pasture_mask(roi=roi, strategy="hybrid")

    stack = build_feature_stack(
        roi=roi,
        target_date=reference_date,
        mask=pasture_mask,
        window_days=window_days,
        annual_productivity_image=None,
    )

    sampled = stack.select(manifest.features).updateMask(pasture_mask.image).reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=roi,
        scale=_INFERENCE_SCALE_M,
        maxPixels=1e13,
    ).getInfo()

    missing = [name for name in manifest.features if sampled.get(name) is None]
    if missing:
        raise CalibratedModelUnavailableError(
            f"Covariáveis sem observação válida no período ({', '.join(missing)}). "
            "Sem elas não há estimativa de biomassa em pé para esta data."
        )

    row = np.array([[float(sampled[name]) for name in manifest.features]])

    predictions = {}
    for label, filename in manifest.quantiles.items():
        model = joblib.load(registry_dir / filename)
        predictions[label] = float(model.predict(row)[0])

    lower, value_per_ha, upper = enforce_monotonic_quantiles(
        predictions.get("p10"), predictions.get("p50"), predictions.get("p90")
    )

    pixel_hectares = ee.Image.pixelArea().divide(10_000)
    valid_area_ha = (
        pixel_hectares.updateMask(pasture_mask.image).rename("valid_ha")
        .reduceRegion(
            reducer=ee.Reducer.sum(), geometry=roi,
            scale=pasture_mask.metadata.resolution_m, maxPixels=1e13,
        ).getInfo().get("valid_ha")
    )

    valid_fraction = _valid_observation_fraction(
        roi=roi, target_date=reference_date, mask=pasture_mask, window_days=window_days
    )

    report = ValidationReport()
    report.merge(observation_quality_flags(valid_fraction))
    report.merge(mask_quality_flags(pasture_mask.metadata.disagreement_fraction))
    report.merge(pasture_mask.quality_flags)
    report.merge(assert_within_envelope("standing_dry_matter_biomass", value_per_ha))

    return BiomassEstimate(
        metric_type="standing_dry_matter_biomass",
        source="Modelo supervisionado calibrado em campo (Sentinel-1/2 + clima + relevo)",
        source_version=manifest.backend,
        period_start=reference_date - datetime.timedelta(days=window_days),
        period_end=reference_date,
        temporal_support="instantaneous",
        value_per_ha=value_per_ha,
        total_value=None if (value_per_ha is None or valid_area_ha is None) else value_per_ha * float(valid_area_ha),
        unit_per_ha="t_DM_ha",
        total_unit="t_DM",
        raster_resolution_m=_INFERENCE_SCALE_M,
        effective_mask_resolution_m=pasture_mask.metadata.resolution_m,
        pasture_mask_source=pasture_mask.metadata.source,
        pasture_mask_reference_year=pasture_mask.metadata.reference_year,
        pasture_mask=pasture_mask.metadata,
        valid_area_ha=None if valid_area_ha is None else float(valid_area_ha),
        valid_observation_fraction=valid_fraction,
        lower_bound_per_ha=lower,
        upper_bound_per_ha=upper,
        uncertainty_method="quantis P10/P90 do modelo quantílico",
        conversion_factors={},
        model_version=manifest.model_version,
        quality_flags=report.quality_flags,
        limitations=[
            f"Validação espacial por fazenda: RMSE {manifest.spatial_cv.get('rmse', float('nan')):.2f} "
            f"t MS/ha em {manifest.n_farms} fazendas.",
            "Estimativa de massa seca em pé; a forragem efetivamente pastejável é menor "
            "(ver forragem disponível).",
        ],
    )


def _valid_observation_fraction(
    roi: ee.Geometry,
    target_date: datetime.date,
    mask: PastureMask,
    window_days: int,
) -> Optional[float]:
    """
    Fração de cenas ópticas aproveitadas na janela, por pixel de pastagem.

    Args:
        roi (ee.Geometry): Região de interesse.
        target_date (datetime.date): Data alvo (fim da janela).
        mask (PastureMask): Máscara de pastagem.
        window_days (int): Tamanho da janela, em dias.

    Returns:
        float | None: Fração entre 0 e 1, ou None quando não há cena na janela.
    """
    start = (target_date - datetime.timedelta(days=window_days)).isoformat()
    end = target_date.isoformat()

    collection = (
        ee.ImageCollection(_S2_ASSET)
        .filterBounds(roi)
        .filterDate(start, end)
        .linkCollection(ee.ImageCollection(_S2_CLOUD_SCORE_ASSET), ["cs_cdf"])
    )

    scene_count = int(collection.size().getInfo())
    if scene_count == 0:
        return None

    valid = (
        collection.map(lambda image: image.select("B8").updateMask(
            image.select("cs_cdf").gte(_CLOUD_SCORE_THRESHOLD)
        ))
        .count()
        .updateMask(mask.image)
        .rename("valid_obs")
        .reduceRegion(
            reducer=ee.Reducer.mean(), geometry=roi,
            scale=_INFERENCE_SCALE_M, maxPixels=1e13,
        ).getInfo().get("valid_obs")
    )

    return None if valid is None else min(1.0, float(valid) / scene_count)
