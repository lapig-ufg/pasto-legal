"""
Módulo core de exportação GEE → xarray/zarr via Xee (issue #112).

Responsabilidades: inicialização do Earth Engine (high-volume endpoint),
carregamento das geometrias de teste, cálculo da grade UTM, exportação do
Satellite Embedding V1 e da série NDVI gapfilled com cast Int16 opcional,
e persistência local em zarr com medição de tempos.

Importado pelos runners (run_benchmark.py) e pelo módulo de classificação.
"""
import ee
import json
import math
import time
import shutil
import traceback

from pathlib import Path
from typing import Dict, List, Tuple

import affine
import xarray as xr

from dotenv import dotenv_values
from agno.utils.log import log_error, log_info


_ROOT = Path(__file__).resolve().parents[2]

_HIGHVOLUME_URL = "https://earthengine-highvolume.googleapis.com"

_MOCK_PATH = _ROOT / "app/utils/mocks/property_mock.json"

_OUTPUT_DIR = _ROOT / "tmp/xee_export"

_EMBEDDING_ASSET = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"

_S2_ASSET = "COPERNICUS/S2_SR_HARMONIZED"

_CLOUD_SCORE_ASSET = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"

_SCALE = 10

_INT16_FACTOR = 10000

_MASK_VALUE = -32768

_CS_CDF_THRESHOLD = 0.60

_HARMONICS = 3


# Credenciais lidas direto do .env: o config do app exige APP_ENV exportado
# (config.py quebra no import sem ele), e este harness roda de forma standalone.
try:
    _env = dotenv_values(_ROOT / ".env")
    _key_file = _env["GEE_KEY_FILE"]
    if not Path(_key_file).is_absolute():
        _key_file = str(_ROOT / _key_file)

    _credentials = ee.ServiceAccountCredentials(_env["GEE_SERVICE_ACCOUNT"], _key_file)
    ee.Initialize(_credentials, project=_env["GEE_PROJECT"], opt_url=_HIGHVOLUME_URL)
    GEE_CONNECTED_FLAG = True
except Exception as error:
    log_error(f"Authentication failed: {error}")
    raise ValueError("GEE_PROJECT/GEE_SERVICE_ACCOUNT/GEE_KEY_FILE devem estar definidos no .env.")


def load_test_properties(mock_path: Path = None) -> List[Dict]:
    """
    Carrega os imóveis rurais de teste de um mock local.

    Aceita geometrias Polygon ou MultiPolygon do GeoJSON. Polígonos simples são
    automaticamente envolvidos em MultiPolygon para compatibilidade com o Earth Engine.

    Args:
        mock_path (Path, optional): Caminho do arquivo mock. Usa _MOCK_PATH se omitido.

    Returns:
        List[Dict]: um dicionário por imóvel com "name", "codigo", "area_ha" e "roi".
    """
    path = mock_path or _MOCK_PATH
    features = json.loads(path.read_text())["features"]

    properties: List[Dict] = []
    for index, feature in enumerate(features):
        geom = feature["geometry"]
        if geom["type"] == "MultiPolygon":
            roi = ee.Geometry.MultiPolygon(geom["coordinates"])
        elif geom["type"] == "Polygon":
            roi = ee.Geometry.MultiPolygon([geom["coordinates"]])
        else:
            raise ValueError(f"Tipo de geometria não suportado: {geom['type']}")

        properties.append({
            "name": f"car_{index + 1}",
            "codigo": feature["properties"]["codigo"],
            "area_ha": feature["properties"]["area"],
            "roi": roi,
        })

    return properties


def _utm_grid(roi: ee.Geometry, crs: str, scale: int) -> Tuple[affine.Affine, int, int]:
    """
    Calcula a grade de pixels do bbox do imóvel projetado no CRS alvo.

    A API do Xee (xee 0.1.1) exige a grade explícita (crs_transform + shape_2d)
    em vez de scale/geometry; por isso derivamos o transform affine e as dimensões.

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


def _persist_zarr(dataset: xr.Dataset, out_path: Path) -> float:
    """
    Persiste o xarray localmente em formato zarr e retorna o tempo gasto.

    Args:
        dataset (xr.Dataset): Dataset já carregado em memória.
        out_path (Path): Caminho do store zarr de saída (sobrescrito se existir).

    Returns:
        float: Tempo de escrita em segundos.
    """
    if out_path.exists():
        shutil.rmtree(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    start = time.perf_counter()
    dataset.to_zarr(out_path, mode="w")
    return time.perf_counter() - start


def _dir_size_mb(path: Path) -> float:
    """Calcula o tamanho em disco (MB) de um store zarr (diretório)."""
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return round(total / 1e6, 3)


def _export_via_xee(name: str, teste: str, collection: ee.ImageCollection,
                    roi: ee.Geometry, stem: str, to_int16: bool, crs: str) -> Dict:
    """
    Exporta uma coleção do GEE via Xee, persiste em zarr e mede os tempos.

    Lógica compartilhada entre os testes: deriva a grade UTM, abre a coleção como
    xarray (Xee), força o download (load), converte para int16 quando pedido e grava
    o zarr — cronometrando separadamente open, exportação (load) e persistência.

    Args:
        name (str): Identificador do imóvel (ex.: "car_1").
        teste (str): Rótulo do teste (para o relatório).
        collection (ee.ImageCollection): Coleção já preparada (cast aplicado pelo caller).
        roi (ee.Geometry): Geometria do imóvel.
        stem (str): Prefixo do nome do arquivo zarr.
        to_int16 (bool): Se True, o dataset é convertido para int16 antes da escrita.
        crs (str): CRS métrico alvo da grade (ex.: "EPSG:32722"), derivado da fonte.

    Returns:
        Dict: métricas do teste (tempos de open/load/persist, shape, tamanho, dtype).
    """
    transform, width, height = _utm_grid(roi=roi, crs=crs, scale=_SCALE)

    start = time.perf_counter()
    dataset = xr.open_dataset(
        collection,
        engine="ee",
        crs=crs,
        crs_transform=transform,
        shape_2d=(width, height),
        mask_and_scale=False,
        ee_mask_value=_MASK_VALUE,
    )
    t_open = time.perf_counter() - start

    start = time.perf_counter()
    dataset = dataset.load()
    t_load = time.perf_counter() - start

    if to_int16:
        dataset = dataset.astype("int16")

    dtype = str(dataset[list(dataset.data_vars)[0]].dtype)

    out_path = _OUTPUT_DIR / f"{name}_{stem}_{dtype}.zarr"
    t_persist = _persist_zarr(dataset=dataset, out_path=out_path)

    result = {
        "imovel": name,
        "teste": teste,
        "dtype": dtype,
        "n_features": len(dataset.data_vars),
        "shape": dict(dataset.sizes),
        "crs": crs,
        "scale_m": _SCALE,
        "t_open_s": round(t_open, 2),
        "t_export_s": round(t_load, 2),
        "t_persist_s": round(t_persist, 2),
        "t_total_s": round(t_open + t_load + t_persist, 2),
        "zarr_mb": _dir_size_mb(out_path),
        "zarr_path": str(out_path.relative_to(_ROOT)),
    }
    log_info(f"[{name}] {teste} {dtype}: {result['t_total_s']}s | {result['zarr_mb']} MB")
    return result


def export_satellite_embedding(name: str, roi: ee.Geometry, year: int = 2025, to_int16: bool = True) -> Dict:
    """
    Exporta as 64 features do Satellite Embedding V1 via Xee e persiste em zarr.

    O cast para Int16 (multiplicação por 10000) é aplicado no lado do Earth Engine
    para que a transferência ocorra em int16 (mais leve que o double nativo). O Xee
    0.1.1 representa os dados como float32 em memória, portanto o dataset é convertido
    de volta para int16 antes da escrita quando to_int16=True.

    Args:
        name (str): Identificador do imóvel (ex.: "car_1").
        roi (ee.Geometry): Geometria do imóvel (área de interesse).
        year (int): Ano alvo da exportação. O mais recente disponível é 2025.
        to_int16 (bool): Se True, converte para Int16; senão mantém float32 (comparação).

    Returns:
        Dict: métricas do teste.
    """
    try:
        collection = (ee.ImageCollection(_EMBEDDING_ASSET)
            .filterBounds(roi)
            .filterDate(f"{year}-01-01", f"{year + 1}-01-01"))

        if collection.size().getInfo() == 0:
            raise ValueError(f"Satellite Embedding {year} indisponível para {name}.")

        crs = _native_crs(collection)

        if to_int16:
            collection = collection.map(lambda img: img.multiply(_INT16_FACTOR)
                .toInt16().copyProperties(img, ["system:time_start"]))

        return _export_via_xee(name=name, teste="satellite_embedding_v1", collection=collection,
                               roi=roi, stem=f"embedding_{year}", to_int16=to_int16, crs=crs)

    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"Falha no Earth Engine ao exportar embedding de {name}: {str(error)}")
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"Erro inesperado ao exportar embedding de {name}: {str(error)}")


def _harmonic_names(base: str, frequencies: ee.List) -> ee.List:
    """Gera os nomes das bandas harmônicas (ex.: cos_1, cos_2, ...)."""
    return ee.List(frequencies).map(lambda i: ee.String(base).cat(ee.Number(i).int()))


def _build_ndvi_gapfilled(roi: ee.Geometry, year: int, harmonics: int = _HARMONICS) -> ee.ImageCollection:
    """
    Constrói a série temporal Sentinel-2 NDVI gapfilled por regressão harmônica.

    Tradução fiel do script EE de referência: mascara nuvens com Cloud Score+ (cs_cdf),
    calcula o NDVI, ajusta um modelo harmônico (constante + tempo + N harmônicos) por
    pixel via regressão linear e devolve, para cada data de aquisição, o NDVI ajustado
    (suave, sem gaps) na banda "NDVI_GAPFILLED".

    Args:
        roi (ee.Geometry): Geometria do imóvel.
        year (int): Ano alvo da série.
        harmonics (int): Número de ciclos por ano modelados (default 3).

    Returns:
        ee.ImageCollection: coleção com uma banda "NDVI_GAPFILLED" por data (~101 datas).
    """
    s2_with_cs = ee.ImageCollection(_S2_ASSET).linkCollection(
        ee.ImageCollection(_CLOUD_SCORE_ASSET), ["cs_cdf"])

    frequencies = ee.List.sequence(1, harmonics)
    cos_names = _harmonic_names("cos_", frequencies)
    sin_names = _harmonic_names("sin_", frequencies)
    independents = ee.List(["constant", "t"]).cat(cos_names).cat(sin_names)
    dependent = "NDVI"

    def mask_s2(image):
        clear = image.select("cs_cdf").gte(_CS_CDF_THRESHOLD)
        optical = image.select("B.*").divide(10000)
        return image.addBands(optical, None, True).updateMask(clear)

    def add_ndvi(image):
        return image.addBands(image.normalizedDifference(["B8", "B4"]).rename("NDVI")).float()

    def add_constant(image):
        return image.addBands(ee.Image(1))

    def add_time(image):
        years = image.date().difference(ee.Date("1970-01-01"), "year")
        return image.addBands(ee.Image(years.multiply(2 * math.pi)).rename("t").float())

    def add_harmonics(image):
        freq_image = ee.Image.constant(frequencies)
        time_radians = ee.Image(image).select("t")
        cosines = time_radians.multiply(freq_image).cos().rename(cos_names)
        sines = time_radians.multiply(freq_image).sin().rename(sin_names)
        return image.addBands(cosines).addBands(sines)

    harmonic = (s2_with_cs
        .filterBounds(roi)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .map(mask_s2).map(add_ndvi).map(add_constant).map(add_time).map(add_harmonics))

    trend = (harmonic.select(independents.add(dependent))
        .reduce(ee.Reducer.linearRegression(independents.length(), 1)))
    coefficients = trend.select("coefficients").arrayProject([0]).arrayFlatten([independents])

    def add_fitted(image):
        fitted = (image.select(independents).multiply(coefficients).reduce("sum")
            .rename("NDVI_GAPFILLED"))
        return image.addBands(fitted).copyProperties(image, ["system:time_start"])

    return harmonic.map(add_fitted).select("NDVI_GAPFILLED")


def export_ndvi_gapfilled(name: str, roi: ee.Geometry, year: int = 2025, to_int16: bool = True) -> Dict:
    """
    Exporta a série temporal Sentinel-2 NDVI gapfilled (~101 datas) via Xee.

    A coleção é modelada por regressão harmônica (ver _build_ndvi_gapfilled) e exportada
    com o eixo temporal preservado: dims (time≈101, y, x) e uma variável NDVI_GAPFILLED.
    O NDVI (faixa [-1, 1]) é limitado e multiplicado por 10000 no Earth Engine para que
    a transferência ocorra em int16.

    Args:
        name (str): Identificador do imóvel (ex.: "car_1").
        roi (ee.Geometry): Geometria do imóvel.
        year (int): Ano alvo da série (default 2025).
        to_int16 (bool): Se True, converte para Int16; senão mantém float32 (comparação).

    Returns:
        Dict: métricas do teste.
    """
    try:
        source = (ee.ImageCollection(_S2_ASSET)
            .filterBounds(roi)
            .filterDate(f"{year}-01-01", f"{year + 1}-01-01"))

        if source.size().getInfo() == 0:
            raise ValueError(f"Sem imagens Sentinel-2 em {year} para {name}.")

        # CRS derivado da banda B8 (a série NDVI calculada perde a projeção -> WGS84).
        crs = _native_crs(source.select("B8"))
        collection = _build_ndvi_gapfilled(roi=roi, year=year)

        if to_int16:
            collection = collection.map(lambda img: img.clamp(-1, 1).multiply(_INT16_FACTOR)
                .toInt16().copyProperties(img, ["system:time_start"]))

        return _export_via_xee(name=name, teste="s2_ndvi_gapfilled", collection=collection,
                               roi=roi, stem=f"ndvi_gapfilled_{year}", to_int16=to_int16, crs=crs)

    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"Falha no Earth Engine ao exportar NDVI gapfilled de {name}: {str(error)}")
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"Erro inesperado ao exportar NDVI gapfilled de {name}: {str(error)}")
