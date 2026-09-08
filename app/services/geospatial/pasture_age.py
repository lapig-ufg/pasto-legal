import time
import traceback

from io import BytesIO
from typing import Dict

import ee
import numpy as np
import PIL.Image
import requests
import xarray as xr

from agno.utils.log import log_error, log_info

from app.services.geospatial.gee import _FEATURE_BUFFER, _IMAGE_DIMENSION, _draw_feature_boundaries, _get_base_image
from app.services.geospatial.image import append_discrete_legend
from app.services.geospatial.pasture_cache import cache_exists, load_cache, save_cache
from app.services.geospatial.pasture_classification import (
    _MAPBIOMAS_ASSET,
    _PASTURE_CLASS,
    _classify,
    _latest_mapbiomas_year,
)
from app.services.geospatial.xee_grid import _native_crs, _utm_grid


_MAPBIOMAS_AGE_ASSET = "projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_age_v2"

_SCALE = 10

_AGE_DICT = {1: "1-10", 2: "10-20", 3: "20-30", 4: "30-40"}

_AGE_PALETTE = ["#ffffcc", "#a1dab4", "#41b6c4", "#225ea8"]


def _age_years_image(roi: ee.Geometry, year: int) -> ee.Image:
    """
    Idade da pastagem (anos), decodificada da banda `year` do asset MapBiomas.

    Mesmo decode usado em `gee.py::get_pasture_age` (offset de 200 + sentinela
    -100 = pastagem já madura, tratada como 40 anos), mas SEM o bucketing final
    em classes — mantemos o valor contínuo para poder somar +1 ano depois.
    """
    age_asset = ee.Image(_MAPBIOMAS_AGE_ASSET).select(year - 2000)
    age = age_asset.subtract(200)
    age = age.where(age.eq(-100), 40)
    return age.clip(roi).rename("idade_anos")


def _area_by_age_class(age_years: "xr.DataArray") -> Dict[str, float]:
    values = age_years.values
    valid = values[~np.isnan(values)]
    if valid.size == 0:
        return {}

    classes = np.digitize(valid, [0, 10, 20, 30, float("inf")])
    pixel_area_ha = (_SCALE ** 2) / 1e4

    result = {}
    for class_id in (1, 2, 3, 4):
        count = int((classes == class_id).sum())
        if count:
            result[_AGE_DICT[class_id]] = round(count * pixel_area_ha, 4)
    return result


def _bucket_age_class(age_years: ee.Image) -> ee.Image:
    """Classe 1-4 (mesmos limites de `_AGE_DICT`) a partir da idade contínua, para visualização."""
    return (
        age_years.where(age_years.gte(1).And(age_years.lte(10)), 1)
        .where(age_years.gt(10).And(age_years.lte(20)), 2)
        .where(age_years.gt(20).And(age_years.lte(30)), 3)
        .where(age_years.gt(30), 4)
    )


def _render_age_image(roi: ee.Geometry, age_years: ee.Image, base_year: int) -> "PIL.Image.Image":
    """Mapa de idade (4 classes) sobreposto ao satélite, mesmo padrão visual das outras camadas."""
    palette_dict = {"1-10": _AGE_PALETTE[0], "10-20": _AGE_PALETTE[1], "20-30": _AGE_PALETTE[2], "30-40": _AGE_PALETTE[3]}

    age_class = _bucket_age_class(age_years)
    overlay = age_class.visualize(min=1, max=4, palette=_AGE_PALETTE)
    base = _get_base_image(roi=roi, year=base_year)
    boundary = _draw_feature_boundaries(roi=roi)

    final_image = base.blend(overlay).blend(boundary).clip(roi.buffer(_FEATURE_BUFFER).bounds())
    url = final_image.getThumbURL({"dimensions": _IMAGE_DIMENSION, "format": "png"})

    response = requests.get(url, timeout=60)
    response.raise_for_status()

    img_pil = PIL.Image.open(BytesIO(response.content))
    return append_discrete_legend(img_pil, "Idade da Pastagem (anos)", palette_dict)


def estimate_pasture_age_on_the_fly(roi: ee.Geometry, car_code: str, pred_year: int = None, train_year: int = None) -> Dict:
    """
    Idade da pastagem on-the-fly: idade do MapBiomas no ano de treino + 1 ano nas
    áreas que continuam pastagem na classificação on-the-fly do ano seguinte;
    pastagem nova (não era pastagem no ano de treino) começa com 1 ano.

    Estratégia igual às demais camadas on-the-fly: toda a combinação (downsample
    implícito do asset 30m para a grade de 10m, soma de +1 ano, máscaras) roda no
    GEE server-side numa única banda; Xee só baixa o resultado final e persiste em
    zarr — cache local (`tmp/`) ou S3 conforme `config.APP_ENV`.

    Args:
        roi (ee.Geometry): Geometria do imóvel (MultiPolygon).
        car_code (str): Código(s) CAR do imóvel — usado como chave de cache.
        pred_year (int, optional): Ano alvo da idade. Default: train_year + 1.
        train_year (int, optional): Ano-base do MapBiomas. Default: ano mais recente disponível.

    Returns:
        Dict: {"area_by_age_class_ha", "pred_year", "train_year", "cached", "imagem"}
    """
    try:
        train_year = train_year or _latest_mapbiomas_year()
        pred_year = pred_year or (train_year + 1)
        cache_key = pred_year

        if cache_exists(car_code, cache_key, kind="age"):
            dataset, image = load_cache(car_code, cache_key, kind="age")
            age_years = dataset["idade_anos"].isel(time=0)
            area_by_class = _area_by_age_class(age_years)
            log_info(f"[{car_code}] pasture age cache hit ({pred_year})")
            return {
                "imagem": image,
                "area_by_age_class_ha": area_by_class,
                "pred_year": pred_year,
                "train_year": train_year,
                "cached": True,
            }

        start = time.perf_counter()

        classified, embedding_check = _classify(roi=roi, train_year=train_year, pred_year=pred_year)

        was_pasture_train = (
            ee.Image(_MAPBIOMAS_ASSET).select(f"classification_{train_year}").eq(_PASTURE_CLASS)
        )
        age_train = _age_years_image(roi=roi, year=train_year)

        new_age = (
            age_train.add(1)
            .updateMask(was_pasture_train)
            .unmask(1)
            .updateMask(classified)
            .min(40)
            .max(1)
            .rename("idade_anos")
        )

        ts = ee.Date(f"{pred_year}-01-01").millis()
        collection = ee.ImageCollection([new_age.toFloat().set("system:time_start", ts)])
        crs = _native_crs(embedding_check)
        transform, width, height = _utm_grid(roi=roi, crs=crs, scale=_SCALE)

        dataset = xr.open_dataset(
            collection, engine="ee", crs=crs, crs_transform=transform, shape_2d=(width, height),
        ).load()

        age_years = dataset["idade_anos"].isel(time=0)
        area_by_class = _area_by_age_class(age_years)

        image = _render_age_image(roi=roi, age_years=new_age, base_year=pred_year)
        save_cache(car_code, cache_key, dataset, image, kind="age")

        log_info(f"[{car_code}] estimate_pasture_age_on_the_fly {pred_year}: {time.perf_counter() - start:.2f}s")

        return {
            "imagem": image,
            "area_by_age_class_ha": area_by_class,
            "pred_year": pred_year,
            "train_year": train_year,
            "cached": False,
        }

    except ValueError as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] {error}")
    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Falha no Earth Engine ao estimar idade da pastagem: {error}")
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Erro inesperado ao estimar idade da pastagem: {error}")
