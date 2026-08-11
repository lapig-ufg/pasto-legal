import time
import traceback

from io import BytesIO
from typing import Dict

import ee
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import PIL.Image
import xarray as xr

from agno.utils.log import log_error, log_info

from app.services.geospatial.pasture_cache import cache_exists, load_cache, save_cache
from app.services.geospatial.xee_grid import _utm_grid


_GPW_UGPP_ASSET = "projects/global-pasture-watch/assets/ggpp-30m/v1/ugpp_m"

_GPW_GRASSLAND_ASSET = "projects/global-pasture-watch/assets/ggc-30m/v1-1/grassland_c"

# Apropriado para pastagens cultivadas de Urochloa brizantha, dominantes no Brasil (MapBiomas Brazil)
_GRASS_LUEMAX_FACTOR = 0.50  # gC/m²/day/MJ

_IPCC_FACTOR = 2.7  # conversão de carbono para biomassa seca

_UNIT_CONVERSION_FACTOR = 0.01  # gC/m² -> ton/ha

DRY_BIOMASS_FACTOR = _GRASS_LUEMAX_FACTOR * _IPCC_FACTOR * _UNIT_CONVERSION_FACTOR

_HISTORY_START_YEAR = 2000

_SCALE = 10


def _utm_epsg_for_roi(roi: ee.Geometry) -> str:
    """
    Deriva o EPSG UTM métrico apropriado a partir do centroide do imóvel.

    Os assets do GPW são nativos em EPSG:4326 (graus) — diferente do Satellite
    Embedding (já distribuído em UTM local por tile), então não há um CRS métrico
    nativo pra reaproveitar aqui. `_utm_grid` precisa de metros, não graus.
    """
    lon, lat = roi.centroid(1).coordinates().getInfo()
    zone = int((lon + 180) // 6) + 1
    hemisphere_base = 32700 if lat < 0 else 32600  # EPSG 327xx (sul) / 326xx (norte)
    return f"EPSG:{hemisphere_base + zone}"


def _latest_gpw_year() -> int:
    """Ano mais recente disponível na coleção ugpp_m do Global Pasture Watch."""
    latest = ee.ImageCollection(_GPW_UGPP_ASSET).sort("system:time_start", False).first()
    return ee.Date(latest.get("system:time_start")).get("year").getInfo()


def _annual_biomass_image(roi: ee.Geometry, year: int) -> ee.Image:
    """
    Biomassa seca de pastagem (t/ha) de um ano, mascarada para pixels de pastagem.

    Fonte: Global Pasture Watch (`ugpp_m` já calibrado + `grassland_c` como máscara),
    convertido com o mesmo fator (LUE=0.5 x IPCC=2.7 x 0.01) usado no restante do app.
    """
    grassland_mask = (ee.ImageCollection(_GPW_GRASSLAND_ASSET)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .first()
        .clip(roi)
        .gte(1))

    return (ee.ImageCollection(_GPW_UGPP_ASSET)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .first()
        .multiply(DRY_BIOMASS_FACTOR)
        .updateMask(grassland_mask)
        .clip(roi)
        .rename("t_ha_year"))


def _yearly_averages(dataset: xr.Dataset) -> Dict[int, float]:
    """Média espacial (t/ha) por ano, ignorando pixels fora da máscara de pastagem (NaN)."""
    years = dataset["time"].dt.year.values
    return {
        int(year): round(float(dataset["t_ha_year"].isel(time=i).mean(skipna=True)), 3)
        for i, year in enumerate(years)
    }


def _render_history_chart(car_code: str, yearly_avg: Dict[int, float]) -> "PIL.Image.Image":
    """Gráfico de linha da série histórica de biomassa média da propriedade."""
    years = sorted(yearly_avg)
    values = [yearly_avg[year] for year in years]

    fig, ax = plt.subplots(figsize=(8, 4), dpi=120)
    ax.plot(years, values, marker="o", color="#2e7d32", linewidth=2)
    ax.set_title(f"Biomassa seca de pastagem — {car_code}")
    ax.set_xlabel("Ano")
    ax.set_ylabel("t/ha (média da propriedade)")
    ax.grid(alpha=0.3)
    fig.tight_layout()

    buffer = BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    buffer.seek(0)

    return PIL.Image.open(buffer)


def estimate_pasture_biomass_history(roi: ee.Geometry, car_code: str) -> Dict:
    """
    Estima a série histórica (2000 até o ano mais recente disponível) de biomassa seca
    de pastagem, pixel a pixel a 10m, dentro da propriedade rural.

    Estratégia: computa tudo no GEE (server-side), exporta via Xee como um único dataset
    zarr — uma banda (`t_ha_year`) com dimensão de tempo (um passo por ano), não bandas
    separadas por ano (custo do Xee é dominado por número de variáveis, não por número
    de datas — ver RESPOSTA_ISSUE.md do #112). Cacheia local (`tmp/`) ou S3, conforme
    `config.APP_ENV` — chamadas seguintes para o mesmo imóvel leem o cache.

    Args:
        roi (ee.Geometry): Geometria do imóvel (MultiPolygon).
        car_code (str): Código(s) CAR do imóvel — usado como chave de cache.

    Returns:
        Dict: {"yearly_avg_t_ha", "history_start_year", "history_end_year", "cached", "imagem"}
            — "yearly_avg_t_ha" mapeia ano -> biomassa média (t/ha) da propriedade (pode ser
            NaN em anos sem nenhum pixel de pastagem mapeado); "imagem" é um PIL.Image.Image
            (gráfico de tendência) pronto para envio.
    """
    try:
        latest_year = _latest_gpw_year()
        cache_key = f"history_{latest_year}"

        if cache_exists(car_code, cache_key, kind="biomass"):
            dataset, image = load_cache(car_code, cache_key, kind="biomass")
            yearly_avg = _yearly_averages(dataset)
            log_info(f"[{car_code}] biomass history cache hit (até {latest_year})")
            return {
                "yearly_avg_t_ha": yearly_avg,
                "history_start_year": _HISTORY_START_YEAR, "history_end_year": latest_year,
                "cached": True, "imagem": image,
            }

        start = time.perf_counter()

        images = []
        for year in range(_HISTORY_START_YEAR, latest_year + 1):
            ts = ee.Date(f"{year}-01-01").millis()
            images.append(_annual_biomass_image(roi, year).toFloat().set("system:time_start", ts))

        collection = ee.ImageCollection(images)
        crs = _utm_epsg_for_roi(roi)
        transform, width, height = _utm_grid(roi=roi, crs=crs, scale=_SCALE)

        dataset = xr.open_dataset(
            collection, engine="ee", crs=crs, crs_transform=transform,
            shape_2d=(width, height),
        ).load()

        yearly_avg = _yearly_averages(dataset)
        image = _render_history_chart(car_code, yearly_avg)
        save_cache(car_code, cache_key, dataset, image, kind="biomass")

        log_info(
            f"[{car_code}] estimate_pasture_biomass_history {_HISTORY_START_YEAR}-{latest_year}: "
            f"{time.perf_counter() - start:.2f}s"
        )

        return {
            "yearly_avg_t_ha": yearly_avg,
            "history_start_year": _HISTORY_START_YEAR, "history_end_year": latest_year,
            "cached": False, "imagem": image,
        }

    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Falha no Earth Engine ao estimar biomassa histórica: {error}")
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(f"[{car_code}] Erro inesperado ao estimar biomassa histórica: {error}")
