"""
Classificação de pastagem via Random Forest — issue #112.

Três estratégias disponíveis (em ordem de velocidade):

    classify_gee        → tudo no GEE server-side; retorna área + PNG (~4–12 s)
    classify_gee_xee    → GEE classifica, Xee baixa o raster resultado (~6–19 s, zarr ~25 KB)
    classify_xee        → Xee baixa o embedding, sklearn classifica local (~65–145 s)

Auxiliar:

    biomass_map         → biomassa MapBiomas da pastagem do imóvel

Metodologia comum às três: amostra MapBiomas (classe 15 = pasto, 300/classe)
num buffer de 2,5 km; treina Random Forest 100 árvores com embedding de 2024;
prevê sobre o embedding de 2025.
"""
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
    _MASK_VALUE,
    _OUTPUT_DIR,
    _SCALE,
    _export_via_xee,
    _native_crs,
    _utm_grid,
)


_MAPBIOMAS_ASSET = "projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_integration_v2"
_BIOMASS_ASSET   = "projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_biomass_v2"
_S2_ASSET        = "COPERNICUS/S2_SR_HARMONIZED"

_PASTURE_CLASS    = 15
_TRAIN_YEAR       = 2024
_PRED_YEAR        = 2025
_SAMPLE_BUFFER_M  = 2500
_SAMPLES_PER_CLASS = 300
_RF_TREES         = 100
_INT16_FACTOR     = 10000
_IMAGE_DIM        = 512
_IMAGE_DIR        = _OUTPUT_DIR / "images"


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _embedding(roi: ee.Geometry, year: int) -> ee.Image:
    """Embedding V1 anual do ano em Int16 (×10000)."""
    image = (ee.ImageCollection(_EMBEDDING_ASSET)
        .filterBounds(roi)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .first())
    return image.multiply(_INT16_FACTOR).toInt16()


def _samples(roi: ee.Geometry, train_year: int) -> Tuple[ee.FeatureCollection, ee.List]:
    """300 amostras/classe (pasto/não-pasto) no buffer de 2,5 km usando MapBiomas + embedding."""
    label = (ee.Image(_MAPBIOMAS_ASSET)
        .select(f"classification_{train_year}")
        .eq(_PASTURE_CLASS)
        .rename("pasto"))
    emb = _embedding(roi=roi, year=train_year)
    fc = label.addBands(emb).stratifiedSample(
        numPoints=_SAMPLES_PER_CLASS,
        classBand="pasto",
        region=roi.buffer(_SAMPLE_BUFFER_M),
        scale=_SCALE,
        seed=42,
        geometries=False,
    )
    return fc, emb.bandNames()


def _to_arrays(samples: ee.FeatureCollection, bandnames: List[str]) -> Tuple[np.ndarray, np.ndarray]:
    """Converte amostras GEE em matrizes numpy (X features, y rótulo)."""
    feats = samples.getInfo()["features"]
    X = np.array([[f["properties"][b] for b in bandnames] for f in feats])
    y = np.array([f["properties"]["pasto"] for f in feats])
    return X, y


def _base_rgb(roi: ee.Geometry, year: int) -> ee.Image:
    """Composição RGB mediana Sentinel-2 (fundo dos mapas)."""
    return (ee.ImageCollection(_S2_ASSET)
        .filterBounds(roi)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        .median()
        .visualize(bands=["B4", "B3", "B2"], min=0, max=3000))


def _boundary(roi: ee.Geometry) -> ee.Image:
    """Contorno vermelho (2 px) do imóvel."""
    empty = ee.Image().byte()
    painted = empty.paint(ee.FeatureCollection([ee.Feature(roi)]), 1, 2)
    return painted.updateMask(painted).visualize(palette=["FF0000"])


def _save_png(image: ee.Image, roi: ee.Geometry, out_path: Path) -> Path:
    """Baixa thumbnail GEE (512 px) e salva como PNG local."""
    url = image.clip(roi.buffer(256).bounds()).getThumbURL({"dimensions": _IMAGE_DIM, "format": "png"})
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    _IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    Image.open(BytesIO(resp.content)).save(out_path)
    return out_path


def _render_map(name: str, prediction: np.ndarray, inside: np.ndarray, pred_year: int) -> Path:
    """Renderiza mapa local: verde=pasto, cinza=não-pasto, transparente=fora do imóvel."""
    rgba = np.zeros((*prediction.shape, 4), dtype=float)
    rgba[inside & (prediction == 0)] = [0.80, 0.80, 0.80, 1.0]
    rgba[inside & (prediction == 1)] = [0.00, 0.78, 0.00, 1.0]
    _IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _IMAGE_DIR / f"{name}_pasto_local_{pred_year}.png"
    plt.imsave(out_path, rgba)
    return out_path


# ---------------------------------------------------------------------------
# Funções públicas de classificação
# ---------------------------------------------------------------------------

def classify_gee(name: str, roi: ee.Geometry,
                 train_year: int = _TRAIN_YEAR, pred_year: int = _PRED_YEAR) -> Dict:
    """Classifica pasto/não-pasto inteiramente no GEE (server-side) e gera mapa PNG."""
    try:
        start = time.perf_counter()

        fc, bandnames = _samples(roi=roi, train_year=train_year)
        classifier = ee.Classifier.smileRandomForest(_RF_TREES).train(fc, "pasto", bandnames)
        classified = _embedding(roi=roi, year=pred_year).classify(classifier).rename("pasto").clip(roi)

        area_ha = (classified.multiply(ee.Image.pixelArea()).divide(1e4)
            .reduceRegion(ee.Reducer.sum(), roi, _SCALE, maxPixels=1e13)
            .get("pasto").getInfo())

        t_classify = round(time.perf_counter() - start, 2)

        overlay = classified.selfMask().visualize(palette=["00c800"])
        image_path = _save_png(
            _base_rgb(roi, pred_year).blend(overlay).blend(_boundary(roi)),
            roi, _IMAGE_DIR / f"{name}_pasto_gee_{pred_year}.png")

        result = {
            "imovel": name, "metodologia": "classify_gee",
            "train_year": train_year, "pred_year": pred_year,
            "area_pasto_ha": round(float(area_ha), 4),
            "t_classify_s": t_classify,
            "t_total_s": round(time.perf_counter() - start, 2),
            "imagem": str(image_path.relative_to(_OUTPUT_DIR.parents[1])),
        }
        log_info(f"[{name}] classify_gee: {result['area_pasto_ha']} ha em {result['t_total_s']}s (classif={result['t_classify_s']}s)")
        return result

    except ee.EEException as e:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{name}] classify_gee falhou no GEE: {e}")
    except Exception as e:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{name}] classify_gee erro inesperado: {e}")


def classify_gee_xee(name: str, roi: ee.Geometry,
                     train_year: int = _TRAIN_YEAR, pred_year: int = _PRED_YEAR) -> Dict:
    """Classifica no GEE e exporta o raster resultado (1 variável binária) via Xee → zarr."""
    try:
        start = time.perf_counter()

        # Pipeline GEE — tudo lazy até o Xee chamar computePixels
        fc, bandnames = _samples(roi=roi, train_year=train_year)
        classifier = ee.Classifier.smileRandomForest(_RF_TREES).train(fc, "pasto", bandnames)
        classified = (_embedding(roi=roi, year=pred_year)
            .classify(classifier).rename("pasto").clip(roi).toInt16())

        ts = ee.Date(f"{pred_year}-01-01").millis()
        collection = ee.ImageCollection([classified.set("system:time_start", ts)])
        crs = _native_crs(
            ee.ImageCollection(_EMBEDDING_ASSET)
            .filterBounds(roi).filterDate(f"{pred_year}-01-01", f"{pred_year + 1}-01-01"))

        # Xee baixa o raster e persiste zarr (aqui o GEE realmente computa tudo)
        xee = _export_via_xee(name=name, teste="classify_gee_xee", collection=collection,
                              roi=roi, stem=f"classified_{pred_year}", to_int16=True, crs=crs)

        # Área calculada localmente a partir do zarr
        zarr_path = _OUTPUT_DIR / f"{name}_classified_{pred_year}_int16.zarr"
        pasto_arr = xr.open_zarr(zarr_path)["pasto"].isel(time=0).values
        area_ha = float((pasto_arr == 1).sum()) * (_SCALE ** 2) / 1e4

        result = {
            "imovel": name, "metodologia": "classify_gee_xee",
            "train_year": train_year, "pred_year": pred_year,
            "area_pasto_ha": round(area_ha, 4),
            "t_xee_open_s": xee["t_open_s"],
            "t_xee_export_s": xee["t_export_s"],
            "t_xee_persist_s": xee["t_persist_s"],
            "t_total_s": round(time.perf_counter() - start, 2),
            "zarr_mb": xee["zarr_mb"],
            "shape": xee["shape"],
        }
        log_info(f"[{name}] classify_gee_xee: {result['area_pasto_ha']} ha em {result['t_total_s']}s")
        return result

    except ee.EEException as e:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{name}] classify_gee_xee falhou no GEE: {e}")
    except Exception as e:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{name}] classify_gee_xee erro inesperado: {e}")


def classify_xee(name: str, roi: ee.Geometry,
                 train_year: int = _TRAIN_YEAR, pred_year: int = _PRED_YEAR) -> Dict:
    """Baixa o embedding (64 variáveis) via Xee e classifica pixel a pixel com sklearn local."""
    try:
        start = time.perf_counter()

        fc, band_list = _samples(roi=roi, train_year=train_year)
        bandnames = band_list.getInfo()
        X, y = _to_arrays(fc, bandnames)
        if X.size == 0:
            raise ValueError(f"Sem amostras de treino para {name}.")

        classifier = RandomForestClassifier(n_estimators=_RF_TREES, random_state=42, n_jobs=-1).fit(X, y)

        crs = _native_crs(ee.ImageCollection(_EMBEDDING_ASSET)
            .filterBounds(roi).filterDate(f"{pred_year}-01-01", f"{pred_year + 1}-01-01"))
        transform, width, height = _utm_grid(roi=roi, crs=crs, scale=_SCALE)

        # Embedding + máscara interna ao polígono (banda inpoly)
        inpoly = ee.Image(1).clip(roi).unmask(0).toInt16().rename("inpoly")
        ts = ee.Date(f"{pred_year}-01-01").millis()
        collection = ee.ImageCollection([
            ee.Image(_embedding(roi=roi, year=pred_year).addBands(inpoly))
            .set("system:time_start", ts)])

        t_export = time.perf_counter()
        dataset = xr.open_dataset(collection, engine="ee", crs=crs, crs_transform=transform,
            shape_2d=(width, height), mask_and_scale=False, ee_mask_value=_MASK_VALUE).load()
        t_export = round(time.perf_counter() - t_export, 2)

        cube   = np.stack([dataset[b].isel(time=0).values for b in bandnames], axis=-1)
        inside = dataset["inpoly"].isel(time=0).values == 1

        t_predict = time.perf_counter()
        prediction = classifier.predict(cube.reshape(-1, len(bandnames))).reshape(cube.shape[:2])
        t_predict = round(time.perf_counter() - t_predict, 2)

        area_ha = float((prediction * inside).sum()) * (_SCALE ** 2) / 1e4
        image_path = _render_map(name, prediction, inside, pred_year)

        result = {
            "imovel": name, "metodologia": "classify_xee",
            "train_year": train_year, "pred_year": pred_year,
            "area_pasto_ha": round(area_ha, 4),
            "t_export_s": t_export, "t_predict_s": t_predict,
            "t_total_s": round(time.perf_counter() - start, 2),
            "imagem": str(image_path.relative_to(_OUTPUT_DIR.parents[1])),
        }
        log_info(f"[{name}] classify_xee: {result['area_pasto_ha']} ha em {result['t_total_s']}s")
        return result

    except ee.EEException as e:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{name}] classify_xee falhou no GEE: {e}")
    except Exception as e:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{name}] classify_xee erro inesperado: {e}")


def biomass_map(name: str, roi: ee.Geometry, year: int = _TRAIN_YEAR) -> Dict:
    """Calcula biomassa de pastagem (MapBiomas) e gera mapa PNG."""
    try:
        start = time.perf_counter()
        biomass = ee.Image(_BIOMASS_ASSET).select(f"biomass_{year}").clip(roi)
        stats = biomass.reduceRegion(
            ee.Reducer.minMax().combine(ee.Reducer.sum(), sharedInputs=True),
            geometry=roi, scale=30, maxPixels=1e13).getInfo()

        min_v = stats.get(f"biomass_{year}_min")
        max_v = stats.get(f"biomass_{year}_max")
        total_ton = round(float(stats.get(f"biomass_{year}_sum") or 0) * 0.09, 2)

        overlay = biomass.visualize(min=min_v or 0, max=max_v or 1,
            palette=["#000033", "#9400D3", "#FF00FF", "#00FFFF", "#FFFFFF"])
        image_path = _save_png(
            _base_rgb(roi, year).blend(overlay).blend(_boundary(roi)),
            roi, _IMAGE_DIR / f"{name}_biomassa_{year}.png")

        result = {
            "imovel": name, "metodologia": "biomass_map",
            "ano": year, "biomassa_total_ton_ms": total_ton,
            "t_total_s": round(time.perf_counter() - start, 2),
            "imagem": str(image_path.relative_to(_OUTPUT_DIR.parents[1])),
        }
        log_info(f"[{name}] biomass_map {year}: {total_ton} t MS em {result['t_total_s']}s")
        return result

    except ee.EEException as e:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{name}] biomass_map falhou no GEE: {e}")
    except Exception as e:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{name}] biomass_map erro inesperado: {e}")
