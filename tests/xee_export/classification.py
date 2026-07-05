import ee
import time
import traceback

from io import BytesIO
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import requests
import xarray as xr

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from PIL import Image
from sklearn.ensemble import RandomForestClassifier
from agno.utils.log import log_error, log_info

from tests.xee_export.export import (
    _EMBEDDING_ASSET,
    _INT16_FACTOR,
    _MASK_VALUE,
    _OUTPUT_DIR,
    _SCALE,
    _native_crs,
    _utm_grid,
)


_MAPBIOMAS_ASSET = "projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_integration_v2"

_BIOMASS_ASSET = "projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_biomass_v2"

_S2_ASSET = "COPERNICUS/S2_SR_HARMONIZED"

_PASTURE_CLASS = 15

_TRAIN_YEAR = 2024

_PRED_YEAR = 2025

_SAMPLE_BUFFER_M = 2500

_SAMPLES_PER_CLASS = 300

_RF_TREES = 100

_IMAGE_DIM = 512

_IMAGE_DIR = _OUTPUT_DIR / "images"


def _embedding_int16(roi: ee.Geometry, year: int) -> ee.Image:
    """Imagem anual do Satellite Embedding V1 do ano, convertida para Int16."""
    image = (ee.ImageCollection(_EMBEDDING_ASSET)
        .filterBounds(roi)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .first())
    return image.multiply(_INT16_FACTOR).toInt16()


def _stratified_samples(roi: ee.Geometry, train_year: int) -> Tuple[ee.FeatureCollection, ee.List]:
    """
    Gera amostras automáticas pasto/não-pasto num buffer ao redor do imóvel.

    Segue a lógica do script de referência (Bernardo): rótulo binário a partir da
    classe Pastagem do MapBiomas no ano de treino e features do Satellite Embedding.

    Args:
        roi (ee.Geometry): Geometria do imóvel.
        train_year (int): Ano de treino (rótulo MapBiomas + embedding).

    Returns:
        Tuple[ee.FeatureCollection, ee.List]: amostras (label + 64 features) e nomes das bandas.
    """
    label = (ee.Image(_MAPBIOMAS_ASSET)
        .select(f"classification_{train_year}")
        .eq(_PASTURE_CLASS)
        .rename("pasto"))

    embedding = _embedding_int16(roi=roi, year=train_year)

    samples = label.addBands(embedding).stratifiedSample(
        numPoints=_SAMPLES_PER_CLASS,
        classBand="pasto",
        region=roi.buffer(_SAMPLE_BUFFER_M),
        scale=_SCALE,
        seed=42,
        geometries=False,
    )
    return samples, embedding.bandNames()


def _base_rgb(roi: ee.Geometry, year: int) -> ee.Image:
    """Composição RGB (mediana Sentinel-2) do ano, para servir de fundo aos mapas."""
    collection = (ee.ImageCollection(_S2_ASSET)
        .filterBounds(roi)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20)))
    return collection.median().visualize(bands=["B4", "B3", "B2"], min=0, max=3000)


def _outline(roi: ee.Geometry) -> ee.Image:
    """Contorno vermelho do imóvel."""
    empty = ee.Image().byte()
    painted = empty.paint(ee.FeatureCollection([ee.Feature(roi)]), 1, 2)
    return painted.updateMask(painted).visualize(palette=["FF0000"])


def _thumb_to_png(image: ee.Image, roi: ee.Geometry, out_path: Path) -> Path:
    """Baixa o thumbnail de uma imagem EE e salva como PNG local."""
    url = image.clip(roi.buffer(256).bounds()).getThumbURL({"dimensions": _IMAGE_DIM, "format": "png"})
    response = requests.get(url, timeout=120)
    response.raise_for_status()

    _IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    Image.open(BytesIO(response.content)).save(out_path)
    return out_path


def classify_gee_native(name: str, roi: ee.Geometry,
                        train_year: int = _TRAIN_YEAR, pred_year: int = _PRED_YEAR) -> Dict:
    """
    Classifica pasto/não-pasto inteiramente no GEE (metodologia server-side).

    Amostra MapBiomas + embedding no ano de treino, treina ee.Classifier.smileRandomForest,
    classifica o embedding do ano-alvo, calcula a área de pastagem e gera a imagem do mapa.

    Args:
        name (str): Identificador do imóvel (ex.: "car_1").
        roi (ee.Geometry): Geometria do imóvel.
        train_year (int): Ano de treino (default 2024).
        pred_year (int): Ano classificado (default 2025).

    Returns:
        Dict: métricas (metodologia, área de pastagem, tempo total, caminho da imagem).
    """
    try:
        start = time.perf_counter()

        samples, bandnames = _stratified_samples(roi=roi, train_year=train_year)
        classifier = ee.Classifier.smileRandomForest(_RF_TREES).train(samples, "pasto", bandnames)

        embedding = _embedding_int16(roi=roi, year=pred_year)
        classified = embedding.classify(classifier).rename("pasto").clip(roi)

        area_ha = (classified.multiply(ee.Image.pixelArea()).divide(1e4)
            .reduceRegion(ee.Reducer.sum(), roi, _SCALE, maxPixels=1e13)
            .get("pasto").getInfo())

        t_total = time.perf_counter() - start

        overlay = classified.selfMask().visualize(palette=["00c800"])
        final = _base_rgb(roi, pred_year).blend(overlay).blend(_outline(roi))
        image_path = _thumb_to_png(final, roi, _IMAGE_DIR / f"{name}_pasto_gee_{pred_year}.png")

        result = {
            "imovel": name,
            "metodologia": "gee_native",
            "train_year": train_year,
            "pred_year": pred_year,
            "area_pasto_ha": round(float(area_ha), 4),
            "t_total_s": round(t_total, 2),
            "imagem": str(image_path.relative_to(_OUTPUT_DIR.parents[1])),
        }
        log_info(f"[{name}] GEE-native: {result['area_pasto_ha']} ha em {result['t_total_s']}s")
        return result

    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"Falha no Earth Engine ao classificar {name} (GEE): {str(error)}")
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"Erro inesperado ao classificar {name} (GEE): {str(error)}")


def _samples_to_arrays(samples: ee.FeatureCollection, bandnames: List[str]) -> Tuple[np.ndarray, np.ndarray]:
    """Converte a coleção de amostras (getInfo) em matrizes X (features) e y (rótulo)."""
    features = samples.getInfo()["features"]
    X = np.array([[feat["properties"][band] for band in bandnames] for feat in features])
    y = np.array([feat["properties"]["pasto"] for feat in features])
    return X, y


def _render_local_map(name: str, prediction: np.ndarray, inside: np.ndarray, pred_year: int) -> Path:
    """Renderiza o mapa classificado local (verde=pasto, cinza=não-pasto) como PNG."""
    rgba = np.zeros((*prediction.shape, 4), dtype=float)
    rgba[inside & (prediction == 0)] = [0.80, 0.80, 0.80, 1.0]
    rgba[inside & (prediction == 1)] = [0.00, 0.78, 0.00, 1.0]

    _IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _IMAGE_DIR / f"{name}_pasto_local_{pred_year}.png"
    plt.imsave(out_path, rgba)
    return out_path


def classify_xee_local(name: str, roi: ee.Geometry,
                       train_year: int = _TRAIN_YEAR, pred_year: int = _PRED_YEAR) -> Dict:
    """
    Classifica pasto/não-pasto localmente (metodologia híbrida via Xee).

    Amostra no GEE (leve) mas treina um sklearn RandomForest local; exporta o embedding
    do ano-alvo via Xee, prevê pixel a pixel na máquina e calcula a área dentro do imóvel.
    O grosso do tempo é a exportação das 64 bandas do embedding.

    Args:
        name (str): Identificador do imóvel (ex.: "car_1").
        roi (ee.Geometry): Geometria do imóvel.
        train_year (int): Ano de treino (default 2024).
        pred_year (int): Ano classificado (default 2025).

    Returns:
        Dict: métricas (metodologia, área, tempos de export/treino/predição, imagem).
    """
    try:
        start = time.perf_counter()

        samples, band_list = _stratified_samples(roi=roi, train_year=train_year)
        bandnames = band_list.getInfo()
        X, y = _samples_to_arrays(samples, bandnames)
        if X.size == 0:
            raise ValueError(f"Sem amostras de treino para {name}.")

        t_train = time.perf_counter()
        classifier = RandomForestClassifier(n_estimators=_RF_TREES, random_state=42, n_jobs=-1).fit(X, y)
        t_train = time.perf_counter() - t_train

        crs = _native_crs(ee.ImageCollection(_EMBEDDING_ASSET)
            .filterBounds(roi).filterDate(f"{pred_year}-01-01", f"{pred_year + 1}-01-01"))
        transform, width, height = _utm_grid(roi=roi, crs=crs, scale=_SCALE)

        inpoly = ee.Image(1).clip(roi).unmask(0).toInt16().rename("inpoly")
        image = _embedding_int16(roi=roi, year=pred_year).addBands(inpoly)
        # Xee requer system:time_start; _embedding_int16 perde a propriedade após toInt16.
        ts = ee.Date(f"{pred_year}-01-01").millis()
        collection = ee.ImageCollection([ee.Image(image).set("system:time_start", ts)])

        t_export = time.perf_counter()
        dataset = xr.open_dataset(collection, engine="ee", crs=crs, crs_transform=transform,
            shape_2d=(width, height), mask_and_scale=False, ee_mask_value=_MASK_VALUE).load()
        t_export = time.perf_counter() - t_export

        cube = np.stack([dataset[band].isel(time=0).values for band in bandnames], axis=-1)
        inside = dataset["inpoly"].isel(time=0).values == 1

        t_predict = time.perf_counter()
        prediction = classifier.predict(cube.reshape(-1, len(bandnames))).reshape(cube.shape[:2])
        t_predict = time.perf_counter() - t_predict

        area_ha = float((prediction * inside).sum()) * (_SCALE ** 2) / 1e4
        t_total = time.perf_counter() - start
        image_path = _render_local_map(name, prediction, inside, pred_year)

        result = {
            "imovel": name,
            "metodologia": "xee_local",
            "train_year": train_year,
            "pred_year": pred_year,
            "area_pasto_ha": round(area_ha, 4),
            "t_train_s": round(t_train, 2),
            "t_export_s": round(t_export, 2),
            "t_predict_s": round(t_predict, 2),
            "t_total_s": round(t_total, 2),
            "imagem": str(image_path.relative_to(_OUTPUT_DIR.parents[1])),
        }
        log_info(f"[{name}] Xee-local: {result['area_pasto_ha']} ha em {result['t_total_s']}s")
        return result

    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"Falha no Earth Engine ao classificar {name} (local): {str(error)}")
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"Erro inesperado ao classificar {name} (local): {str(error)}")


def biomass_image(name: str, roi: ee.Geometry, year: int = _TRAIN_YEAR) -> Dict:
    """
    Gera o mapa temático de biomassa de pastagem (MapBiomas) para o imóvel.

    Args:
        name (str): Identificador do imóvel (ex.: "car_1").
        roi (ee.Geometry): Geometria do imóvel.
        year (int): Ano da biomassa (default 2024, o mais recente do asset).

    Returns:
        Dict: métricas (biomassa total em toneladas de matéria seca, imagem).
    """
    try:
        biomass = ee.Image(_BIOMASS_ASSET).select(f"biomass_{year}").clip(roi)

        stats = biomass.reduceRegion(ee.Reducer.minMax().combine(ee.Reducer.sum(), sharedInputs=True),
            geometry=roi, scale=30, maxPixels=1e13).getInfo()

        min_val = stats.get(f"biomass_{year}_min")
        max_val = stats.get(f"biomass_{year}_max")
        total_ton = round(float(stats.get(f"biomass_{year}_sum") or 0) * 0.09, 2)

        palette = ["#000033", "#9400D3", "#FF00FF", "#00FFFF", "#FFFFFF"]
        overlay = biomass.visualize(min=min_val or 0, max=max_val or 1, palette=palette)
        final = _base_rgb(roi, year).blend(overlay).blend(_outline(roi))
        image_path = _thumb_to_png(final, roi, _IMAGE_DIR / f"{name}_biomassa_{year}.png")

        result = {
            "imovel": name,
            "metodologia": "biomassa",
            "ano": year,
            "biomassa_total_ton_ms": total_ton,
            "imagem": str(image_path.relative_to(_OUTPUT_DIR.parents[1])),
        }
        log_info(f"[{name}] biomassa {year}: {total_ton} t MS")
        return result

    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"Falha no Earth Engine ao gerar biomassa de {name}: {str(error)}")
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"Erro inesperado ao gerar biomassa de {name}: {str(error)}")
