import time
import traceback

from io import BytesIO
from typing import Dict, Tuple

import affine
import ee
import PIL
import requests
import xarray as xr

from agno.utils.log import log_error, log_info

from app.utils.scripts.gee_scripts import _FEATURE_BUFFER, _IMAGE_DIMENSION, _draw_feature_boundaries, _get_base_image
from app.utils.scripts.pasture_cache_storage import cache_exists, load_cache, save_cache


_EMBEDDING_ASSET = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"

_MAPBIOMAS_ASSET = "projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_integration_v2"

_PASTURE_CLASS = 15

_SAMPLE_BUFFER_M = 2500

_SAMPLES_PER_CLASS = 300

_RF_TREES = 100

_INT16_FACTOR = 10000

_SCALE = 10

_MASK_VALUE = -32768


def _utm_grid(roi: ee.Geometry, crs: str, scale: int) -> Tuple[affine.Affine, int, int]:
    """
    Calcula a grade de pixels do bbox do imóvel projetado no CRS alvo.

    A API do Xee (0.1.1) exige a grade explícita (crs_transform + shape_2d) em
    vez de scale/geometry, por isso derivamos o transform affine e as dimensões.

    Args:
        roi (ee.Geometry): Geometria do imóvel.
        crs (str): CRS métrico alvo (ex.: "EPSG:32722").
        scale (int): Tamanho do pixel em metros.

    Returns:
        Tuple[affine.Affine, int, int]: transform, largura (x) e altura (y) em pixels.
    """
    projection = ee.Projection(crs)
    ring = ee.List(roi.bounds(1).transform(projection, 1).coordinates().get(0)).getInfo()

    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]

    x_min = (min(xs) // scale) * scale
    x_max = -(-max(xs) // scale) * scale
    y_min = (min(ys) // scale) * scale
    y_max = -(-max(ys) // scale) * scale

    width = round((x_max - x_min) / scale)
    height = round((y_max - y_min) / scale)
    transform = affine.Affine(scale, 0, x_min, 0, -scale, y_max)

    return transform, width, height


def _native_crs(collection: ee.ImageCollection) -> str:
    """Retorna o CRS nativo (métrico) da primeira imagem da coleção."""
    return collection.first().select(0).projection().getInfo()["crs"]


def _embedding(roi: ee.Geometry, year: int) -> ee.Image:
    """Embedding V1 anual do ano em Int16 (×10000)."""
    image = (ee.ImageCollection(_EMBEDDING_ASSET)
        .filterBounds(roi)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .first())
    return image.multiply(_INT16_FACTOR).toInt16()


def _samples(roi: ee.Geometry, train_year: int) -> Tuple[ee.FeatureCollection, ee.List]:
    """300 amostras/classe (pasto/não-pasto) num buffer de 2,5km, usando MapBiomas + embedding."""
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


def _latest_mapbiomas_year() -> int:
    """Ano mais recente com banda 'classification_YYYY' disponível no asset do MapBiomas."""
    bands = ee.Image(_MAPBIOMAS_ASSET).bandNames().getInfo()
    years = [int(band.replace("classification_", "")) for band in bands if band.startswith("classification_")]
    return max(years)


def _area_ha_from_pasto(pasto: xr.DataArray) -> float:
    """Área em hectares a partir da banda binária de pasto (1 = pasto)."""
    return float((pasto.values == 1).sum()) * (_SCALE ** 2) / 1e4


def _render_classification_image(roi: ee.Geometry, classified: ee.Image, base_year: int) -> "PIL.Image.Image":
    """Sobrepõe o pasto classificado (verde) na imagem de satélite + contorno da propriedade."""
    overlay = classified.selfMask().visualize(palette=["00c800"])
    base = _get_base_image(roi=roi, year=base_year)
    boundary = _draw_feature_boundaries(roi=roi)

    final_image = base.blend(overlay).blend(boundary).clip(roi.buffer(_FEATURE_BUFFER).bounds())
    url = final_image.getThumbURL({"dimensions": _IMAGE_DIMENSION, "format": "png"})

    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return PIL.Image.open(BytesIO(response.content))


def classify_pasture_on_the_fly(roi: ee.Geometry, car_code: str, pred_year: int = None, train_year: int = None) -> Dict:
    """
    Classifica pasto/não-pasto para o ano mais recente disponível e mapeia a propriedade.

    Estratégia vencedora medida em tests/xee_export/ (ver RESPOSTA_ISSUE.md): a
    classificação roda inteiramente no GEE (server-side, `smileRandomForest`,
    treinado com amostras do MapBiomas + Satellite Embedding do ano de treino) e
    prevê sobre o embedding do ano seguinte. O Xee só baixa o raster resultado
    (1 banda binária) para um cache em zarr + png (`pasture_cache_storage`:
    local em `tmp/` no `development`, bucket S3 em `production`/`stagging`) —
    chamadas seguintes para o mesmo imóvel/ano leem o cache e não tocam o GEE.

    Args:
        roi (ee.Geometry): Geometria do imóvel (MultiPolygon).
        car_code (str): Código(s) CAR do imóvel — usado como chave de cache.
        pred_year (int, optional): Ano alvo da classificação. Usa train_year + 1 se omitido.
        train_year (int, optional): Ano de treino (amostras MapBiomas + embedding). Usa o ano mais recente disponível no MapBiomas se omitido.

    Returns:
        Dict: {"area_pasto_ha", "pred_year", "train_year", "cached", "imagem"} — "imagem" é um PIL.Image.Image pronto para envio.
    """
    try:
        train_year = train_year or _latest_mapbiomas_year()
        pred_year = pred_year or (train_year + 1)

        if cache_exists(car_code, pred_year):
            dataset, image = load_cache(car_code, pred_year)
            pasto = dataset["pasto"].isel(time=0)
            area_ha = _area_ha_from_pasto(pasto)
            log_info(f"[{car_code}] pasture cache hit ({pred_year}): {area_ha} ha")
            return {
                "area_pasto_ha": round(area_ha, 4),
                "pred_year": pred_year, "train_year": train_year,
                "cached": True, "imagem": image,
            }

        start = time.perf_counter()

        embedding_check = (ee.ImageCollection(_EMBEDDING_ASSET)
            .filterBounds(roi).filterDate(f"{pred_year}-01-01", f"{pred_year + 1}-01-01"))
        if embedding_check.size().getInfo() == 0:
            raise ValueError(f"Satellite Embedding {pred_year} ainda não disponível para este imóvel.")

        fc, bandnames = _samples(roi=roi, train_year=train_year)
        classifier = ee.Classifier.smileRandomForest(_RF_TREES).train(fc, "pasto", bandnames)
        classified = (_embedding(roi=roi, year=pred_year)
            .classify(classifier).rename("pasto").clip(roi).toInt16())

        ts = ee.Date(f"{pred_year}-01-01").millis()
        collection = ee.ImageCollection([classified.set("system:time_start", ts)])
        crs = _native_crs(embedding_check)
        transform, width, height = _utm_grid(roi=roi, crs=crs, scale=_SCALE)

        dataset = xr.open_dataset(
            collection, engine="ee", crs=crs, crs_transform=transform,
            shape_2d=(width, height), mask_and_scale=False, ee_mask_value=_MASK_VALUE,
        ).load().astype("int16")

        pasto = dataset["pasto"].isel(time=0)
        area_ha = _area_ha_from_pasto(pasto)

        image = _render_classification_image(roi=roi, classified=classified, base_year=pred_year)
        save_cache(car_code, pred_year, dataset, image)

        log_info(f"[{car_code}] classify_pasture_on_the_fly {pred_year}: {area_ha} ha em {time.perf_counter() - start:.2f}s")

        return {
            "area_pasto_ha": round(area_ha, 4),
            "pred_year": pred_year, "train_year": train_year,
            "cached": False, "imagem": image,
        }

    except ValueError as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] {error}")
    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Falha no Earth Engine ao classificar pastagem: {error}")
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Erro inesperado ao classificar pastagem: {error}")
