import ee
import PIL
import datetime
import requests
import traceback

from io import BytesIO
from typing import List, Optional, Tuple

import numpy as np
from PIL import ImageDraw, ImageFont
from shapely.geometry import shape as shapely_shape

from semente.logging import log_error, log_warning

from semente.configs.config import config

from domain.services.geospatial import raster_layers, raster_render
from domain.services.geospatial.pasture_cache import dataset_exists, load_dataset, save_dataset
from domain.services.geospatial.xee_grid import RasterGrid, grid_for_roi
from domain.services.geospatial.pasture_biomass import DRY_BIOMASS_FACTOR, _annual_biomass_image, _latest_gpw_year
from domain.schemas.property_stats import PropertyStats, PastureStats, TopographicStats
from domain.schemas.property_stats import (
    Value, 
    BiomassStats,
    AgeData,
    AgeStats,
    VigorData,
    VigorStats,
    LULCData,
    LULCStats,
    SoilData,
    SoilStats
    )


_FEATURE_BUFFER = 256

_IMAGE_DIMENSION = 512

# Higher resolution used on the property confirmation image so that the
# paddock labels remain readable after WhatsApp compression.
_OVERVIEW_IMAGE_DIMENSION = 1024

_LABEL_FONT_PATH = "assets/fonts/DejaVuSans-Bold.ttf"

_HIGHVOLUME_URL = "https://earthengine-highvolume.googleapis.com"

_BIOMASS_CACHE_VERSION = "v1"
_BIOMASS_PALETTE = ["#f75639", "#eef79c", "#f5d570", "#8aa637", "#0b391f"]

try:
    credentials = ee.ServiceAccountCredentials(config.GEE_SERVICE_ACCOUNT, config.GEE_KEY_FILE)
    ee.Initialize(credentials, project=config.GEE_PROJECT, opt_url=_HIGHVOLUME_URL)
except Exception as e:
    log_error(f"Authentication failed: {e}")
    raise ValueError("GEE_PROJECT environment variables must be set.")


def _get_base_image(roi: ee.Geometry, year: int = None) -> ee.Image:
    """
    Gera imagem de satélite (mediana) em cor real para um polígono.
    
    Args:
        roi (ee.Geometry): Região de interesse (polígono da fazenda).
        year (int, optional): Ano desejado. Se None, usa a data atual.
        
    Returns:
        ee.Image: Imagem Earth Engine pronta para visualização (RGB, 8-bit).
    """
    try:
        if not year:
            date = datetime.date.today()
        else:
            date = datetime.date(year, 12, 31)  

        s_date = ee.Date.fromYMD(date.year - 1, date.month, 1)
        e_date = s_date.advance(1, 'year')

        # Função de escalonamento para Landsat C2 L2
        def apply_scale_landsat(image: ee.Image):
            """Applies the scale/offset factors to the optical bands (SR_B.*) of a Landsat Collection 2 Level-2 image."""
            optical_bands = image.select('SR_B.').multiply(0.0000275).add(-0.2)
            return image.addBands(optical_bands, None, True)

        needs_scaling = False
        
        if date.year >= 2016:
            asset = "COPERNICUS/S2_SR_HARMONIZED"
            cloud_prop = "CLOUDY_PIXEL_PERCENTAGE"
            visualize_params = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}
            
        elif date.year >= 2013:
            asset = "LANDSAT/LC08/C02/T1_L2"
            cloud_prop = "CLOUD_COVER"
            visualize_params = {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 0.0, "max": 0.3}
            needs_scaling = True
            
        elif date.year == 2012:
            asset = "LANDSAT/LE07/C02/T1_L2"
            cloud_prop = "CLOUD_COVER"
            visualize_params = {"bands": ["SR_B3", "SR_B2", "SR_B1"], "min": 0.0, "max": 0.3}
            needs_scaling = True
            
        elif date.year >= 2003:
            asset = "LANDSAT/LT05/C02/T1_L2"
            cloud_prop = "CLOUD_COVER"
            visualize_params = {"bands": ["SR_B3", "SR_B2", "SR_B1"], "min": 0.0, "max": 0.3}
            needs_scaling = True
            
        else:
            asset = "LANDSAT/LE07/C02/T1_L2"
            cloud_prop = "CLOUD_COVER"
            visualize_params = {"bands": ["SR_B3", "SR_B2", "SR_B1"], "min": 0.0, "max": 0.3}
            needs_scaling = True

        image_collection = (ee.ImageCollection(asset)
            .filterBounds(roi)
            .filterDate(s_date, e_date)
            .filter(ee.Filter.lt(cloud_prop, 10))
        )

        if needs_scaling:
            image_collection = image_collection.map(apply_scale_landsat)

        image = image_collection.median().visualize(**visualize_params)
        
        return image
    
    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Falha ao processar as coordenadas no satélite. "
            f"Verifique se as coordenadas da área estão corretas. Detalhes: {str(error)}"
        )
    except requests.exceptions.HTTPError as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"O servidor de imagens do satélite retornou um erro. "
            f"Tente solicitar a imagem novamente em alguns instantes. Detalhes: {str(error)}"
        )
    except requests.exceptions.RequestException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Não foi possível baixar a imagem por falha de conexão. "
            f"Pode haver instabilidade na rede. Detalhes: {str(error)}"
        )
    except PIL.UnidentifiedImageError as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"O arquivo recebido do satélite está corrompido ou num formato inesperado. Detalhes: {str(error)}"
        )
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Ocorreu um erro inesperado ao gerar a imagem da fazenda. Detalhes: {str(error)}"
        )


def _draw_feature_boundaries(roi) -> ee.Image:
    """
    Draws a red outline of a polygon on an empty image.

    Args:
        roi (ee.Geometry): Region of interest to be outlined.

    Returns:
        ee.Image: RGB image containing only the outline (red, 3px width).
    """
    empty = ee.Image().byte()
    outline = empty.paint(ee.FeatureCollection([ee.Feature(roi)]), 1, 3)
    outline = outline.updateMask(outline)
    outline_rgb = outline.visualize(**{"palette":['FF0000']})

    return outline_rgb


def retrieve_feature_images(coords: List[List[List[List[float]]]]) -> List[PIL.Image]:
    """
    Gera imagens de satélite individuais para cada polígono da propriedade rural.

    A imagem base é lida do cache zarr e o contorno é desenhado localmente.
    """
    try:
        result_imgs = []
        for _coords in coords:
            roi = ee.Geometry.MultiPolygon([_coords])
            grid = grid_for_roi(roi, scale=10, buffer_m=_FEATURE_BUFFER)
            feature_key = raster_layers.feature_key_from_coords([_coords])
            base_rgb = raster_layers.get_base_raster(
                roi=roi, feature_key=feature_key, grid=grid
            )

            image = PIL.Image.fromarray(base_rgb, mode="RGB")
            image = raster_render.resize_map(image, _IMAGE_DIMENSION)
            image = raster_render.draw_outline(
                image,
                [_coords],
                raster_render.grid_for_image_size(grid, image.size),
                width=3,
            )
            result_imgs.append(image)

        return result_imgs

    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Falha ao processar as coordenadas no satélite. "
            f"Verifique se as coordenadas da área estão corretas. Detalhes: {str(error)}"
        )
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Ocorreu um erro inesperado ao gerar a imagem da fazenda. Detalhes: {str(error)}"
        )


def retrieve_plain_satellite_image(coords: List[List[List[List[float]]]]) -> List[PIL.Image]:
    """
    Gera imagens de satélite individuais para cada polígono da propriedade rural,
    sem contorno ou qualquer sobreposição (imagem "crua"), a partir do cache zarr.
    """
    try:
        result_imgs = []
        for _coords in coords:
            roi = ee.Geometry.MultiPolygon([_coords])
            grid = grid_for_roi(roi, scale=10, buffer_m=_FEATURE_BUFFER)
            feature_key = raster_layers.feature_key_from_coords([_coords])
            base_rgb = raster_layers.get_base_raster(
                roi=roi, feature_key=feature_key, grid=grid
            )
            image = PIL.Image.fromarray(base_rgb, mode="RGB")
            result_imgs.append(raster_render.resize_map(image, _IMAGE_DIMENSION))

        return result_imgs

    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Falha ao processar as coordenadas no satélite. "
            f"Verifique se as coordenadas da área estão corretas. Detalhes: {str(error)}"
        )
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Ocorreu um erro inesperado ao gerar a imagem da fazenda. Detalhes: {str(error)}"
        )


def _paddock_centroid(coords: List[List[List[List[float]]]]) -> Tuple[float, float]:
    """
    Returns the (latitude, longitude) representative point of a paddock
    (GeoJSON MultiPolygon nesting: ``[[shell, hole, ...], ...]``), always
    inside the geometry.

    Note: shapely's ``MultiPolygon(coords)`` constructor expects a different
    nesting (``[(shell, holes), ...]``), so the geometry is built through
    ``shapely.geometry.shape`` instead.
    """
    geometry = shapely_shape({"type": "MultiPolygon", "coordinates": coords})
    point = geometry.representative_point()
    return float(point.y), float(point.x)


def _draw_paddock_labels(
    image: PIL.Image,
    region_bounds: Tuple[float, float, float, float],
    labels: List[Tuple[str, Tuple[float, float]]],
) -> PIL.Image:
    """
    Draws the paddock labels centered on each paddock representative point.

    The satellite thumbnail is rendered for ``region_bounds`` (west, south,
    east, north) preserving its aspect ratio, so the coordinate-to-pixel
    mapping is a linear interpolation over that rectangle.

    Args:
        image: The satellite thumbnail (RGB).
        region_bounds: The geographic bounds rendered in the thumbnail.
        labels: List of (text, (latitude, longitude)) pairs.

    Returns:
        PIL.Image: A copy of the image with the labels drawn.
    """
    west, south, east, north = region_bounds
    width, height = image.size

    span_lon = east - west
    span_lat = north - south
    if span_lon <= 0 or span_lat <= 0:
        return image

    font_size = max(12, int(height * 0.022))
    try:
        font = ImageFont.truetype(_LABEL_FONT_PATH, font_size)
    except IOError:
        font = ImageFont.load_default()

    labeled = image.copy()
    draw = ImageDraw.Draw(labeled)

    for text, (latitude, longitude) in labels:
        x = int((longitude - west) / span_lon * width)
        y = int((north - latitude) / span_lat * height)
        if not (0 <= x < width and 0 <= y < height):
            continue

        # Keep only the paddock number ("Paddock_12" -> "12") and shrink the
        # stroke so the label fits inside small paddocks.
        number = text.rsplit("_", 1)[-1]

        draw.text(
            (x, y),
            number,
            font=font,
            fill=(255, 255, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0),
            anchor="mm",
        )

    return labeled


def retrieve_property_overview_image(
    property_coords: List[List[List[List[float]]]],
    paddocks: Optional[List[Tuple[List[List[List[List[float]]]], str]]] = None,
    dimension: int = _OVERVIEW_IMAGE_DIMENSION,
) -> PIL.Image:
    """
    Generates a single satellite image for the property registration
    confirmation, highlighting the property boundaries.

    For a single polygon the image shows its boundary. When paddocks are
    provided, all paddock boundaries are drawn on the same image with a
    numeric label (the paddock number only) at the center of each one,
    using a higher resolution so the labels remain readable.

    Args:
        property_coords: The rural property MultiPolygon coordinates.
        paddocks: Optional list of (paddock coords, label) pairs.
        dimension: Longest side of the generated image, in pixels.

    Returns:
        PIL.Image: Satellite image with boundaries (and paddock labels).

    Raises:
        RuntimeError: On Earth Engine processing, image server, connection,
            image format or unexpected failures.
    """
    try:
        roi = ee.Geometry.MultiPolygon(property_coords)
        grid = grid_for_roi(roi, scale=10, buffer_m=_FEATURE_BUFFER)
        feature_key = raster_layers.feature_key_from_coords(property_coords)
        base_rgb = raster_layers.get_base_raster(
            roi=roi, feature_key=feature_key, grid=grid
        )

        img_pil = PIL.Image.fromarray(base_rgb, mode="RGB")
        img_pil = raster_render.resize_map(img_pil, dimension)
        outline_grid = raster_render.grid_for_image_size(grid, img_pil.size)

        if paddocks:
            for coords, _label in paddocks:
                img_pil = raster_render.draw_outline(
                    img_pil, [coords], outline_grid, width=3
                )
        else:
            img_pil = raster_render.draw_outline(
                img_pil, property_coords, outline_grid, width=3
            )

        if paddocks:
            region = roi.buffer(_FEATURE_BUFFER).bounds()
            bounds_info = region.coordinates().getInfo()[0]
            west = min(coord[0] for coord in bounds_info)
            east = max(coord[0] for coord in bounds_info)
            south = min(coord[1] for coord in bounds_info)
            north = max(coord[1] for coord in bounds_info)

            labels = [
                (label, _paddock_centroid(coords))
                for coords, label in paddocks
            ]
            img_pil = _draw_paddock_labels(
                img_pil, (west, south, east, north), labels
            )

        return img_pil

    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Falha ao processar as coordenadas no satélite. "
            f"Verifique se as coordenadas da área estão corretas. Detalhes: {str(error)}"
        )
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Ocorreu um erro inesperado ao gerar a imagem da fazenda. Detalhes: {str(error)}"
        )


def _reference_period(year: int, month: int) -> tuple[datetime.date, datetime.date]:
    """
    Regra do mês de referência: o período acumulado é o mês anterior ao mês/ano informado.

    Args:
        year (int): Ano de referência.
        month (int): Mês de referência.

    Returns:
        tuple[datetime.date, datetime.date]: (início, fim) com fim exclusivo.
    """
    start_year, start_month = (year - 1, 12) if month == 1 else (year, month - 1)
    start_date = datetime.date(start_year, start_month, 1)
    end_date = datetime.date(year, month, 1)
    return start_date, end_date


def _get_t2g_biomass_image(
    roi,
    start_year: int,
    start_month: int,
    start_day: int,
    end_year: int,
    end_month: int,
    end_day: int,
    pasture_mask: Optional[ee.Image] = None,
    apply_mask: bool = True,
):
    """
    Computes the accumulated dry biomass image (ton/ha) from UGPP productivity.

    Uses the Time2Graze collection (10m UGPP) accumulated over the given period,
    multiplied by the scale factor, LUEmax, the IPCC factor (C -> dry biomass) and
    the ton/ha conversion factor, masked by `pasture_mask` or, by default, by Global
    Pasture Watch grassland areas.

    Args:
        roi (ee.Geometry): Region of interest (farm polygon).
        start_year (int): Start year of the accumulation period.
        start_month (int): Start month of the accumulation period.
        start_day (int): Start day of the accumulation period.
        end_year (int): End year (exclusive) of the accumulation period.
        end_month (int): End month (exclusive) of the accumulation period.
        end_day (int): End day (exclusive) of the accumulation period.
        pasture_mask (ee.Image, optional): Pasture mask; defaults to the GPW grassland map.
        apply_mask (bool): When False, returns the unmasked biomass accumulation.

    Returns:
        tuple[ee.Image, int, int]: (biomass image 'tonC_hec', start year, start month),
        or None if there is no UGPP data for the period/region.
    """
    # DRY_BIOMASS_FACTOR (LUEmax x fator carbono x conversão gC/m²->ton/ha) vem
    # de pasture_biomass.py — mesma constante usada na série histórica GPW, para
    # as duas fontes (T2G mensal e GPW anual) nunca divergirem silenciosamente.
    UGPP_SCALE_FACTOR = 0.1

    start_date = ee.Date.fromYMD(start_year, start_month, start_day)
    end_date = ee.Date.fromYMD(end_year, end_month, end_day)

    n_days = ee.Number(end_date.difference(start_date, 'day'))

    ugpp = ee.ImageCollection("projects/wri-lcl-time2graze/assets/ugpp_prod_10m_v1").filter(ee.Filter.date('2025-07-03', '2025-07-04').Not())
    ugpp_col = ugpp.filterBounds(roi).filterDate(start_date, end_date)

    # Máscara de pastagem no mesmo ano do período de biomassa pedido (não mais fixa em 2024) —
    # limitada ao último ano publicado pelo GPW, já que o asset não cobre anos futuros.
    if apply_mask:
        if pasture_mask is not None:
            grassland_mask = pasture_mask.gte(1)
        else:
            mask_year = min(start_year, _latest_gpw_year())
            grassland_asset = ee.ImageCollection("projects/global-pasture-watch/assets/ggc-30m/v1-1/grassland_c")
            grassland_mask = grassland_asset.filterBounds(roi).filterDate(f'{mask_year}-01-01', f'{mask_year + 1}-01-01').first().gte(1)

    if ugpp_col.size().eq(0).getInfo():
        log_error(
            f"_get_t2g_biomass_image returned None: empty UGPP collection "
            f"for roi={roi}, period={start_year}/{start_month}/{start_day} - {end_year}/{end_month}/{end_day}"
        )
        return None

    biomass_image: ee.Image = (
        ugpp_col.mean()
        .multiply(ee.Image(n_days))
        .multiply(ee.Image(UGPP_SCALE_FACTOR))
        .multiply(DRY_BIOMASS_FACTOR)
        .clip(roi)
        .rename("tonC_hec")
    )
    if apply_mask:
        biomass_image = biomass_image.updateMask(grassland_mask)

    return biomass_image, start_year, start_month


def _get_t2g_biomass_array(
    roi: ee.Geometry,
    feature_key: str,
    month: int,
    year: int,
    grid: Optional[RasterGrid] = None,
):
    """Returns the unmasked T2G biomass array cached on the canonical grid."""
    grid = grid or grid_for_roi(roi, scale=10, buffer_m=_FEATURE_BUFFER)
    cache_key = raster_layers.layer_cache_key(
        [year, month], grid, _BIOMASS_CACHE_VERSION
    )

    if dataset_exists(feature_key, cache_key, kind="biomass_t2g"):
        dataset = load_dataset(feature_key, cache_key, kind="biomass_t2g")
        values = raster_layers.clean_mask_values(
            dataset["tonC_hec"].isel(time=0).values
        )
        return (
            values,
            int(dataset.attrs.get("target_year", year)),
            int(dataset.attrs.get("target_month", month)),
        )

    start_date, end_date = _reference_period(year, month)
    result = _get_t2g_biomass_image(
        roi,
        start_date.year, start_date.month, start_date.day,
        end_date.year, end_date.month, end_date.day,
        apply_mask=False,
    )

    if result is None:
        fallback_month, fallback_year = (12, year - 1) if month == 1 else (month - 1, year)
        start_date, end_date = _reference_period(fallback_year, fallback_month)
        result = _get_t2g_biomass_image(
            roi,
            start_date.year, start_date.month, start_date.day,
            end_date.year, end_date.month, end_date.day,
            apply_mask=False,
        )

    if result is None:
        return None

    biomass_image, target_year, target_month = result
    dataset = raster_layers.download_image_dataset(
        biomass_image, grid, band_name="tonC_hec", dtype="float32"
    )
    dataset.attrs.update(
        {
            "target_year": int(target_year),
            "target_month": int(target_month),
            "requested_year": int(year),
            "requested_month": int(month),
            "grid_hash": grid.hash,
        }
    )
    save_dataset(feature_key, cache_key, dataset, kind="biomass_t2g")

    return (
        raster_layers.clean_mask_values(dataset["tonC_hec"].isel(time=0).values),
        int(target_year),
        int(target_month),
    )


def _get_pasture_mask_array(
    roi: ee.Geometry,
    feature_key: str,
    grid: RasterGrid,
) -> np.ndarray:
    from domain.services.geospatial.pasture_mask import get_pasture_mask_array

    try:
        return get_pasture_mask_array(roi=roi, feature_key=feature_key, grid=grid)
    except Exception as error:
        log_warning(
            f"pasture mask indisponível, usando a área da propriedade sem máscara: {error}"
        )
        return np.ones((grid.height, grid.width), dtype=np.int16)


def retrieve_t2g_biomass_image(
    coords: List[List[List[List[float]]]],
    month: int,
    year: int,
    pasture_mask: Optional[ee.Image] = None,
    feature_key: Optional[str] = None,
) -> tuple[PIL.Image.Image, int, int] | None:
    """
    Generates a satellite image with the T2G (Time2Graze) biomass layer overlaid,
    relative to the reference month (the month before the one given), with a colorbar.

    The biomass raster is downloaded once from GEE into a zarr cache and masked
    locally by the cached pasture classification, then rendered over the cached
    satellite base with PIL.

    Args:
        coords: List of coordinates representing the farm MultiPolygon.
        month (int): Reference month (the accumulation uses the previous month).
        year (int): Reference year.
        pasture_mask: Deprecated; kept for backward compatibility.
        feature_key: Stable cache key for the property.

    Returns:
        tuple[PIL.Image.Image, int, int]: (final image with satellite, biomass,
        outline and colorbar, effective accumulation year and month), or None
        when no UGPP data is available for the period. If the chosen month has
        no data, falls back once to the previous month before returning None.

    Raises:
        ValueError: If the area contains no mapped pasture with computable biomass.
        RuntimeError: On processing, server, connection or unexpected failures
            (with a message ready to be relayed to the user).
    """
    try:
        roi = ee.Geometry.MultiPolygon(coords)
        feature_key = feature_key or raster_layers.feature_key_from_coords(coords)
        grid = grid_for_roi(roi, scale=10, buffer_m=_FEATURE_BUFFER)

        result = _get_t2g_biomass_array(
            roi=roi,
            feature_key=feature_key,
            month=month,
            year=year,
            grid=grid,
        )
        if result is None:
            return None

        biomass, target_year, target_month = result
        pasture = _get_pasture_mask_array(roi, feature_key, grid)
        masked = np.where(pasture == 1, biomass, np.nan)

        if not np.isfinite(masked).any():
            raise ValueError(
                "Não foi possível calcular a biomassa. A área pode não conter pastagem mapeada."
            )

        min_bio_val = float(np.nanmin(masked))
        max_bio_val = float(np.nanmax(masked))

        base_rgb = raster_layers.get_base_raster(
            roi=roi, feature_key=feature_key, year=target_year, grid=grid
        )
        img = raster_render.render_continuous_map(
            base_rgb=base_rgb,
            values=masked,
            coords=coords,
            grid=grid,
            palette=_BIOMASS_PALETTE,
            title=f"Biomassa ({target_year}/{target_month}) - T2G",
            unit="ton/ha",
            vmin=min_bio_val,
            vmax=max_bio_val,
            dimension=_IMAGE_DIMENSION,
            ndigits=1,
        )

        return img, target_year, target_month

    except ValueError as error:
        log_error(traceback.format_exc())
        raise error
    except ee.EEException:
        log_error(traceback.format_exc())
        raise RuntimeError(
            "Peça desculpas e informe que houve uma falha de processamento.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except Exception:
        log_error(traceback.format_exc())
        raise RuntimeError(
            "Peça desculpas e informe que houve um erro inesperado.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )

def retrieve_gpw_biomass_image(
    coords: List[List[List[List[float]]]],
    year: int = None,
    feature_key: Optional[str] = None,
) -> PIL.Image.Image:
    """
    Mapa de biomassa seca de pastagem (Global Pasture Watch), usado como fallback
    quando o T2G não cobre a propriedade (fora da lista fixa de tiles) — cobertura
    nacional/global, sem essa limitação. Se `year` for omitido, usa o ano mais
    recente disponível no GPW. O raster é cacheado em zarr e renderizado localmente.
    """
    roi = ee.Geometry.MultiPolygon(coords)
    feature_key = feature_key or raster_layers.feature_key_from_coords(coords)
    grid = grid_for_roi(roi, scale=10, buffer_m=_FEATURE_BUFFER)

    if year is None:
        year = _latest_gpw_year()

    key = raster_layers.layer_cache_key([year], grid, "v1")
    values, grid = raster_layers.get_layer_array(
        roi=roi,
        feature_key=feature_key,
        kind="biomass_gpw",
        key=key,
        image_factory=lambda: _annual_biomass_image(roi, year),
        band_name="t_ha_year",
        grid=grid,
        scale=10,
    )

    masked = np.where(np.isfinite(values), values, np.nan)
    if not np.isfinite(masked).any():
        raise ValueError(
            "Não foi possível calcular a biomassa. A área pode não conter pastagem mapeada."
        )

    min_bio_val = float(np.nanmin(masked))
    max_bio_val = float(np.nanmax(masked))
    palette = ["#000033", "#9400D3", "#FF00FF", "#00FFFF", "#FFFFFF"]

    base_rgb = raster_layers.get_base_raster(
        roi=roi, feature_key=feature_key, year=year, grid=grid
    )
    return raster_render.render_continuous_map(
        base_rgb=base_rgb,
        values=masked,
        coords=coords,
        grid=grid,
        palette=palette,
        title=f"Biomassa\n({year}) - GPW",
        unit="ton/ha/ano",
        vmin=min_bio_val,
        vmax=max_bio_val,
        dimension=_IMAGE_DIMENSION,
    )


BIOMASS_VIDEO_MIN_YEAR = 2025

BIOMASS_VIDEO_PALETTE = ['#000033', '#9400D3', '#FF00FF', '#00FFFF', '#FFFFFF']


def _iterate_reference_months(
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
) -> tuple[list[tuple[int, int]], tuple[int, int], tuple[int, int]]:
    """
    Valida e normaliza o intervalo de meses de referência para o vídeo de biomassa.

    Regras:
        - O ano inicial não pode ser anterior a 2025 (início da série UGPP/T2G).
        - O intervalo final é limitado ao mês de referência atual (mês corrente,
          o mesmo limite aplicado por `_reference_period`); pedidos além disso
          são ajustados (clamp) para o limite, sem erro.
        - Meses fora de 1-12 geram erro.

    Args:
        start_year (int): Ano inicial solicitado.
        start_month (int): Mês inicial solicitado.
        end_year (int): Ano final solicitado (inclusivo).
        end_month (int): Mês final solicitado (inclusivo).

    Returns:
        tuple: (lista de (ano, mês) de referência, início efetivo, fim efetivo).

    Raises:
        ValueError: Se ano/mês inicial for inválido, meses fora de 1-12 ou
            intervalo vazio após o clamp.
    """
    today = datetime.date.today()

    if not 1 <= start_month <= 12 or not 1 <= end_month <= 12:
        raise ValueError("Os meses informados devem estar entre 1 (janeiro) e 12 (dezembro).")

    if start_year < BIOMASS_VIDEO_MIN_YEAR:
        raise ValueError(
            f"Os dados de biomassa (T2G) estão disponíveis apenas a partir de "
            f"{BIOMASS_VIDEO_MIN_YEAR}. Informe um ano inicial maior ou igual a {BIOMASS_VIDEO_MIN_YEAR}."
        )

    requested_end = (end_year, end_month)
    current_limit = (today.year, today.month)

    if requested_end > current_limit:
        log_warning(
            f"_iterate_reference_months: end {end_year}/{end_month} clamped to current reference month {current_limit[0]}/{current_limit[1]}"
        )
        end_year, end_month = current_limit

    effective_start = (start_year, start_month)
    effective_end = (end_year, end_month)

    if effective_start > effective_end:
        raise ValueError(
            "O mês/ano inicial deve ser anterior ou igual ao mês/ano final "
            "(considerando que o período final é limitado ao mês atual)."
        )

    months: list[tuple[int, int]] = []
    year, month = effective_start
    while (year, month) <= effective_end:
        months.append((year, month))
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1

    return months, effective_start, effective_end


def _retrieve_t2g_biomass_video_cached(
    coords: List[List[List[List[float]]]],
    feature_key: str,
    months: list[tuple[int, int]],
    effective_start: tuple[int, int],
    effective_end: tuple[int, int],
) -> tuple[bytes, tuple[int, int], tuple[int, int], list[tuple[int, int]], float, float] | None:
    roi = ee.Geometry.MultiPolygon(coords)
    grid = grid_for_roi(roi, scale=10, buffer_m=_FEATURE_BUFFER)
    pasture = _get_pasture_mask_array(roi, feature_key, grid)

    frames_data: list[tuple[int, np.ndarray, int, int]] = []
    for ref_year, ref_month in months:
        result = _get_t2g_biomass_array(
            roi=roi,
            feature_key=feature_key,
            month=ref_month,
            year=ref_year,
            grid=grid,
        )
        if result is None:
            log_warning(
                f"retrieve_t2g_biomass_video: sem dados UGPP para {ref_month}/{ref_year}; frame ignorado"
            )
            continue

        biomass, acc_year, acc_month = result
        masked = np.where(pasture == 1, biomass, np.nan)
        if not np.isfinite(masked).any():
            log_warning(
                f"retrieve_t2g_biomass_video: estatísticas vazias para {ref_month}/{ref_year}; frame ignorado"
            )
            continue

        frames_data.append((ref_year, masked, acc_year, acc_month))

    if len(frames_data) < 2:
        log_warning(
            f"retrieve_t2g_biomass_video: apenas {len(frames_data)} frame(s) com dados UGPP "
            f"para o período {effective_start} - {effective_end}; retornando None"
        )
        return None

    global_min = min(float(np.nanmin(frame)) for _, frame, _, _ in frames_data)
    global_max = max(float(np.nanmax(frame)) for _, frame, _, _ in frames_data)
    frame_months = [(acc_year, acc_month) for _, _, acc_year, acc_month in frames_data]

    base_by_year = {
        year: raster_layers.get_base_raster(
            roi=roi, feature_key=feature_key, year=year, grid=grid
        )
        for year in {acc_year for _, _, acc_year, _ in frames_data}
    }

    frames = []
    for _ref_year, values, acc_year, _acc_month in frames_data:
        overlay = raster_render.continuous_rgba(
            values, BIOMASS_VIDEO_PALETTE, global_min, global_max
        )
        frames.append(
            raster_render.render_rgba_frame(
                base_rgb=base_by_year[acc_year],
                values=values,
                overlay=overlay,
                coords=coords,
                grid=grid,
                dimension=_IMAGE_DIMENSION,
            )
        )

    buffer = BytesIO()
    frames[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=1000,
        loop=0,
    )
    return buffer.getvalue(), effective_start, effective_end, frame_months, global_min, global_max


def retrieve_t2g_biomass_video(
    coords: List[List[List[List[float]]]],
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
    pasture_mask: Optional[ee.Image] = None,
    feature_key: Optional[str] = None,
) -> tuple[bytes, tuple[int, int], tuple[int, int]] | None:
    """
    Gera um GIF animado da biomassa acumulada (ton/ha) mês a mês, usando a
    série T2G (Time2Graze/UGPP), sobre a imagem de satélite e com o contorno
    da propriedade em cada frame, com escala de cores fixa entre os frames.

    Para cada mês de referência no intervalo (inclusivo), acumula o mês anterior
    via `_reference_period` + `_get_t2g_biomass_image` e empilha os frames
    compostos como no mapa estático de biomassa: imagem de satélite de fundo,
    camada de biomassa visualizada com a mesma paleta e contorno vermelho da
    propriedade. Meses sem dados UGPP são ignorados.

    Args:
        coords: Lista de coordenadas representando o MultiPolygon da fazenda.
        start_year (int): Ano do primeiro mês de referência (>= 2025).
        start_month (int): Mês do primeiro mês de referência (1-12).
        end_year (int): Ano do último mês de referência (limitado ao mês atual).
        end_month (int): Mês do último mês de referência (1-12, limitado ao mês atual).
        pasture_mask (ee.Image, optional): Máscara de pastagem; padrão: mapa GPW.

    Returns:
        tuple[bytes, tuple, tuple, list, float, float] | None: (GIF em bytes,
        (ano, mês) inicial efetivo, (ano, mês) final efetivo, lista de
        (ano, mês) de acumulação de cada frame, biomassa mínima global,
        biomassa máxima global), ou None quando menos de 2 meses possuem
        dados UGPP.

    Raises:
        ValueError: Se o intervalo informado for inválido (ver `_iterate_reference_months`).
        RuntimeError: Em falhas de processamento, servidor, conexão ou erros
            inesperados (com mensagem pronta para ser repassada ao usuário).
    """
    try:
        months, effective_start, effective_end = _iterate_reference_months(
            start_year, start_month, end_year, end_month
        )

        feature_key = feature_key or raster_layers.feature_key_from_coords(coords)
        return _retrieve_t2g_biomass_video_cached(
            coords=coords,
            feature_key=feature_key,
            months=months,
            effective_start=effective_start,
            effective_end=effective_end,
        )

    except ValueError as error:
        raise error
    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Falha ao processar as coordenadas no satélite. "
            f"Verifique se as coordenadas da área estão corretas. Detalhes: {str(error)}"
        )
    except requests.exceptions.HTTPError as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"O servidor de imagens do satélite retornou um erro ao gerar o vídeo. "
            f"Tente solicitar o vídeo novamente em alguns instantes. Detalhes: {str(error)}"
        )
    except requests.exceptions.RequestException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Não foi possível baixar o vídeo por falha de conexão. "
            f"Pode haver instabilidade na rede. Detalhes: {str(error)}"
        )
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Ocorreu um erro inesperado ao gerar o vídeo da biomassa. Detalhes: {str(error)}"
        )

def retrieve_feature_soil_texture_image(
    coords: List[List[List[List[float]]]],
    feature_key: Optional[str] = None,
) -> PIL.Image.Image:
    """
    Generates a satellite image with the soil texture layer (0-30cm, MapBiomas
    Collection 3) overlaid, with a discrete legend of the texture classes.

    The class raster is cached as zarr and rendered locally over the cached
    satellite base.
    """
    try:
        class_colors = {
            1: "#707070",
            2: "#a83800",
            3: "#aa8686",
            4: "#298289",
            5: "#fffe73",
            6: "#d7c5a5",
        }
        class_labels = {
            1: "Afloramento",
            2: "Muito Argiloso",
            3: "Argila",
            4: "Siltoso",
            5: "Arenoso",
            6: "Médio",
        }

        roi = ee.Geometry.MultiPolygon(coords)
        feature_key = feature_key or raster_layers.feature_key_from_coords(coords)
        grid = grid_for_roi(roi, scale=10, buffer_m=_FEATURE_BUFFER)

        def _soil_image() -> ee.Image:
            asset = ee.ImageCollection(
                "projects/mapbiomas-public/assets/brazil/soil/collection3/"
                "mapbiomas_brazil_collection3_soil_textural_group_v1"
            )
            image = asset.toBands().select(
                ["textural_group_000_030_v1_textural_group"]
            )
            return image.rename(["soil_texture"])

        key = raster_layers.layer_cache_key([], grid, "v1")
        values, grid = raster_layers.get_layer_array(
            roi=roi,
            feature_key=feature_key,
            kind="soil",
            key=key,
            image_factory=_soil_image,
            band_name="soil_texture",
            grid=grid,
            scale=10,
        )

        values = np.nan_to_num(values, nan=0).astype(int)
        base_rgb = raster_layers.get_base_raster(
            roi=roi, feature_key=feature_key, grid=grid
        )
        return raster_render.render_discrete_map(
            base_rgb=base_rgb,
            values=values,
            coords=coords,
            grid=grid,
            class_colors=class_colors,
            class_labels=class_labels,
            title="Textura Solo",
            dimension=_IMAGE_DIMENSION,
        )

    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Falha ao processar as coordenadas no satélite. "
            f"Verifique se as coordenadas da área estão corretas. Detalhes: {str(error)}"
        )
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Ocorreu um erro inesperado ao gerar a imagem da fazenda. Detalhes: {str(error)}"
        )


def retrieve_pasture_vigor_image(
    coords: List[List[List[List[float]]]],
    year: int = 2024,
    feature_key: Optional[str] = None,
) -> PIL.Image:
    """
    Gera uma imagem de satélite com a camada de vigor de pastagem sobreposta,
    baseada na geometria da propriedade rural fornecida.

    O raster de classes é cacheado em zarr e renderizado localmente.
    """
    try:
        class_colors = {1: "#d7191c", 2: "#fdae61", 3: "#1a9641"}
        class_labels = {1: "Baixo", 2: "Médio", 3: "Alto"}

        roi = ee.Geometry.MultiPolygon(coords)
        feature_key = feature_key or raster_layers.feature_key_from_coords(coords)
        grid = grid_for_roi(roi, scale=10, buffer_m=_FEATURE_BUFFER)

        def _vigor_image() -> ee.Image:
            asset = ee.Image(
                "projects/mapbiomas-public/assets/brazil/lulc/collection10/"
                "mapbiomas_brazil_collection10_pasture_vigor_v3"
            )
            return asset.select(year - 2000).rename("vigor_class")

        key = raster_layers.layer_cache_key([year], grid, "v1")
        values, grid = raster_layers.get_layer_array(
            roi=roi,
            feature_key=feature_key,
            kind="vigor_static",
            key=key,
            image_factory=_vigor_image,
            band_name="vigor_class",
            grid=grid,
            scale=10,
        )

        values = np.nan_to_num(values, nan=0).astype(int)
        base_rgb = raster_layers.get_base_raster(
            roi=roi, feature_key=feature_key, grid=grid
        )
        return raster_render.render_discrete_map(
            base_rgb=base_rgb,
            values=values,
            coords=coords,
            grid=grid,
            class_colors=class_colors,
            class_labels=class_labels,
            title="Vigor da Pastagem",
            dimension=_IMAGE_DIMENSION,
        )

    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Falha ao processar as coordenadas no satélite. "
            f"Verifique se as coordenadas da área estão corretas. Detalhes: {str(error)}"
        )
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Ocorreu um erro inesperado ao gerar a imagem da fazenda. Detalhes: {str(error)}"
        )


def get_biomass(
    roi: ee.Geometry,
    month: int,
    year: int,
    pasture_mask: Optional[ee.Image] = None,
    feature_key: Optional[str] = None,
) -> BiomassStats:
    """
    Computes pasture dry biomass accumulated in the reference month (the month
    before the one given), using the Time2Graze collection (10m UGPP).

    When ``feature_key`` is given, the biomass and pasture mask are read from
    the zarr cache and the total is computed locally. Otherwise the legacy
    server-side path is kept.

    When there is no UGPP data for the period/region, falls back to the MapBiomas
    asset (2024 annual biomass, 0.09 scale, value accumulated over the year).

    Args:
        roi (ee.Geometry): Region of interest (farm polygon).
        month (int): Reference month (the accumulation uses the previous month).
        year (int): Reference year.
        pasture_mask (ee.Image, optional): Deprecated EE mask.
        feature_key (str, optional): Stable cache key for the property.

    Returns:
        BiomassStats: Observation year and accumulated value with unit
        ("tonelada(s) de matéria seca acumulada no mês ..." or "... no ano").
    """
    month_dict = {
        1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
        7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
    }

    if feature_key:
        grid = grid_for_roi(roi, scale=10, buffer_m=_FEATURE_BUFFER)
        result = _get_t2g_biomass_array(
            roi=roi, feature_key=feature_key, month=month, year=year, grid=grid
        )

        if result is not None:
            biomass, target_year, target_month = result
            pasture = _get_pasture_mask_array(roi, feature_key, grid)
            masked = np.where(pasture == 1, biomass, np.nan)
            if np.isfinite(masked).any():
                pixel_area_ha = (grid.scale ** 2) / 1e4
                biomass_value = float(np.nansum(masked) * pixel_area_ha)
                return BiomassStats(
                    observation_year=target_year,
                    period="mensal",
                    amount=Value(
                        value=biomass_value,
                        unity=f"tonelada(s) de matéria seca acumulada no mês de {month_dict[target_month]}",
                    ),
                )
            log_warning(
                "get_biomass: T2G sem pixels de pastagem após a máscara; usando fallback GPW"
            )

        # GPW fallback also read from the raster cache.
        gpw_year = _latest_gpw_year()
        key = raster_layers.layer_cache_key([gpw_year], grid, "v1")
        values, grid = raster_layers.get_layer_array(
            roi=roi,
            feature_key=feature_key,
            kind="biomass_gpw",
            key=key,
            image_factory=lambda: _annual_biomass_image(roi, gpw_year),
            band_name="t_ha_year",
            grid=grid,
            scale=10,
        )
        pixel_area_ha = (grid.scale ** 2) / 1e4
        biomass_value = float(np.nansum(values) * pixel_area_ha)
        return BiomassStats(
            observation_year=gpw_year,
            period="anual",
            amount=Value(
                value=biomass_value,
                unity="tonelada(s) de matéria seca acumulada no ano",
            ),
        )

    start_date, end_date = _reference_period(year, month)
    result = _get_t2g_biomass_image(
        roi,
        start_date.year, start_date.month, start_date.day,
        end_date.year, end_date.month, end_date.day,
        pasture_mask=pasture_mask,
    )

    # Fallback pro Global Pasture Watch (cobertura nacional/global) se o T2G não cobrir a propriedade
    if result is None:
        year = _latest_gpw_year()

        last_biomass = _annual_biomass_image(roi, year)

        # Densidade (t/ha) x área real do pixel (pixelArea(), não uma constante fixa de
        # ha/pixel) -> total em toneladas. Área de pixel varia com latitude/projeção;
        # uma constante fixa (ex.: 0,09 ha pro pixel "de 30m") erra sistematicamente
        # quanto mais longe a propriedade estiver da latitude usada pra calibrá-la.
        total_image = last_biomass.multiply(ee.Image.pixelArea().divide(10000)).rename('t_ha_year')

        stats = total_image.reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=roi,
            scale=30,  # resolução nativa do GPW (ggpp-30m/ggc-30m)
            maxPixels=1e13
        )

        biomass_value = stats.getInfo().get('t_ha_year', 0)

        return BiomassStats(
            observation_year=year, period="anual",
            amount=Value(value=biomass_value, unity="tonelada(s) de matéria seca acumulada no ano"),
        )
    else:
        last_biomass, target_year, target_month = result

        # Mesmo motivo do ramo GPW acima: área real do pixel, não uma constante fixa.
        total_image = last_biomass.multiply(ee.Image.pixelArea().divide(10000)).rename('tonC_hec')

        stats = total_image.reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=roi,
            scale=10,
            maxPixels=1e13
        )

        biomass_value = stats.getInfo().get('tonC_hec', 0)

        return BiomassStats(
            observation_year=target_year, period="mensal",
            amount=Value(value=biomass_value, unity=f"tonelada(s) de matéria seca acumulada no mês de {month_dict[target_month]}"),
        )


def _latest_asset_year(asset_id: str, base_year: int = 2000) -> int:
    """
    Último ano disponível num asset MapBiomas cujas bandas são indexadas por
    posição (banda 0 = base_year, banda 1 = base_year+1, ...) — caso do
    pasture_age_v2, pasture_vigor_v3 e integration_v2 usados abaixo.
    """
    band_count = ee.Image(asset_id).bandNames().size().getInfo()
    return base_year + band_count - 1


_AGE_ASSET = 'projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_age_v2'
_VIGOR_ASSET = 'projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_vigor_v3'
_LULC_ASSET = 'projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_integration_v2'

# Banda 0 desses dois assets é classification_1985 (não 2000, como no de vigor) —
# usado tanto pro clamp de "último ano disponível" quanto pra seleção de banda por índice.
_AGE_ASSET_BASE_YEAR = 1985
_LULC_ASSET_BASE_YEAR = 1985


def get_pasture_age(roi: ee.Geometry, year: int, month: int = None) -> AgeStats:
    """
    Computes pasture area (ha) per age class via MapBiomas (Collection 10).

    Raw ages are reclassified into 4 ranges (1-10, 10-20, 20-30, 30-40 years)
    plus a 5th class for pixels that hit the asset's sentinel value (pasture
    already mature at the start of the series, real age unknown and possibly
    much older than 40) — kept separate so a precisely computed 30-40 is never
    mixed with a censored, indeterminate age.

    Args:
        roi (ee.Geometry): Region of interest (farm polygon).
        year (int): Reference year of the mapping (band `year - 1985`).
        month (int, optional): Ignored; kept for signature compatibility.

    Returns:
        AgeStats: Observation year and list of areas per age range (ha).
    """
    AGE_DICT = {'1':'1-10', '2':'10-20', '3':'20-30', '4':'30-40', '5':'≥40 (idade real indeterminada)'}

    target_year = min(year, _latest_asset_year(_AGE_ASSET, base_year=_AGE_ASSET_BASE_YEAR))
    age_asset = ee.Image(_AGE_ASSET)
    raw_age = age_asset.select(target_year - _AGE_ASSET_BASE_YEAR).subtract(200)
    is_censored = raw_age.eq(-100)

    last_age = raw_age.where(is_censored, 40)
    last_age = (last_age.where(last_age.gte(1).And(last_age.lte(10)), 1)
                        .where(last_age.gt(10).And(last_age.lte(20)), 2)
                        .where(last_age.gt(20).And(last_age.lte(30)), 3)
                        .where(last_age.gt(30).And(last_age.lte(40)), 4)
                        .where(is_censored, 5)
                ).rename('Anos')

    areaImg = ee.Image.pixelArea().divide(10000).addBands(last_age)

    stats = areaImg.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName='class'),
        geometry=roi,
        scale=30,
        maxPixels=1e13
    )

    groups_info = stats.get('groups').getInfo()
    age_data_list: List[AgeData] = []

    if groups_info:
        for group in groups_info:
            class_id = str(int(group['class']))
            class_name = AGE_DICT.get(class_id)
            area_value = round(float(group['sum']))

            age_data_list.append(AgeData(age=class_name, amount=Value(value=area_value, unity="hectares (ha)")))

    return AgeStats(observation_year=target_year, data=age_data_list)

def get_pasture_vigor(roi: ee.Geometry, year: int, month: int = None) -> VigorStats:
    """
    Computes pasture area (ha) per vigor class via MapBiomas (Collection 10).

    Classes: 1 = Low (severe degradation, potentially biological),
    2 = Medium (moderate degradation), 3 = High (high vegetative vigor).

    Args:
        roi (ee.Geometry): Region of interest (farm polygon).
        year (int): Reference year of the mapping (band `year - 2000`).
        month (int, optional): Ignored; kept for signature compatibility.

    Returns:
        VigorStats: Observation year and list of areas per vigor class (ha).
    """
    VIGOR_DICT = {
        '1':'Baixo: pastagens com baixo vigor vegetativo e indícios de degradação severa, potencialmente biológica.',
        '2':'Médio: pastagens com médio vigor vegativo e indícios de degração moderada.',
        '3':'Alto: pastagens com alto vigor vegetativo.'
    }

    target_year = min(year, _latest_asset_year(_VIGOR_ASSET))
    vigor_asset = ee.Image(_VIGOR_ASSET)
    last_vigor = vigor_asset.select(target_year - 2000)

    areaImg = ee.Image.pixelArea().divide(10000).addBands(last_vigor)

    stats = areaImg.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName='class'),
        geometry=roi,
        scale=30,
        maxPixels=1e13
    )

    groups_info = stats.get('groups').getInfo()
    vigor_data_list: List[VigorData] = []

    if groups_info:
        for group in groups_info:
            class_id = str(int(group['class']))
            vigor_name = VIGOR_DICT.get(class_id)
            area_value = round(float(group['sum']), 2)

            vigor_data_list.append(VigorData(vigor=vigor_name, amount=Value(value=area_value, unity="hectares (ha)")))

    return VigorStats(observation_year=target_year, data=vigor_data_list)

def get_land_use_land_cover(roi: ee.Geometry, year: int, month: int = None) -> LULCStats:
    """
    Computes area (ha) per land use and land cover class via MapBiomas
    (Collection 10, annual integration).

    Args:
        roi (ee.Geometry): Region of interest (farm polygon).
        year (int): Reference year of the mapping (band `year - 1985`).
        month (int, optional): Ignored; kept for signature compatibility.

    Returns:
        LULCStats: Observation year and list of areas per LULC class (ha).
    """
    CLASSES = {
        '3':'Formação Florestal', '4':'Formação Savânica', '5':'Mangue',
        '6':'Floresta Alagável', '9':'Silvicultura', '11':'Campo Alagado e Área Pantanosa',
        '12':'Formação Campestre', '15':'Pastagem', '19':'Lavoura Temporária',
        '20':'Cana', '29':'Afloramento Rochoso', '39':'Soja', '46':'Café',
        '32':'Apicum', '35':'Dendê', '36':'Lavoura Perene', '40':'Arroz',
        '41':'Outras Lavouras Temporárias', '47':'Citrus',
        '48':'Outras Lavouras Perenes', '49':'Restinga Arbórea', '50':'Restinga Herbácea',
        '62':'Algodão', '21':'Mosaico de Usos', '23':'Praia, Duna e Areal',
        '24':'Área Urbanizada', '30':'Mineração', '75':'Usina Fotovoltaica (beta)',
        '25':'Outras Áreas não Vegetadas', '26':"Corpo D'água", '33':'Rio, Lago e Oceano',
        '31':'Aquicultura', '27':'Não observado'
    }

    target_year = min(year, _latest_asset_year(_LULC_ASSET, base_year=_LULC_ASSET_BASE_YEAR))
    class_asset = ee.Image(_LULC_ASSET)
    last_class = class_asset.select(target_year - _LULC_ASSET_BASE_YEAR)

    areaImg = ee.Image.pixelArea().divide(10000).addBands(last_class)

    stats = areaImg.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName='class'),
        geometry=roi,
        scale=30,
        maxPixels=1e13
    )

    groups_info = stats.get('groups').getInfo()
    lulc_class_data_list: List[LULCData] = []

    if groups_info:
        for group in groups_info:
            class_id = str(int(group['class']))
            class_name = CLASSES.get(class_id)
            area_value = round(float(group['sum']), 2)
            
            lulc_class_data_list.append(LULCData(lulc_class=class_name, amount=Value(value=area_value, unity="hectares")))

    return LULCStats(observation_year=target_year, data=lulc_class_data_list)


_SOIL_TEXTURE_ASSET = "projects/mapbiomas-public/assets/brazil/soil/collection3/mapbiomas_brazil_collection3_soil_textural_group_v1"

_SOIL_TEXTURE_CLASSES = {
    '1': 'Afloramento', '2': 'Muito Argiloso', '3': 'Argila',
    '4': 'Siltoso', '5': 'Arenoso', '6': 'Médio',
}


def get_soil_texture_stats(roi: ee.Geometry) -> SoilStats:
    """
    Computes area (ha) per soil textural class (0-30cm) via MapBiomas (Collection 3).

    Mesmo asset e mesmas classes de `retrieve_feature_soil_texture_image` — a
    textura do solo não varia por ano, então não há um `year` de referência
    real; usa-se o ano corrente só como data do relatório.

    Args:
        roi (ee.Geometry): Region of interest (farm polygon).

    Returns:
        SoilStats: Observation year (ano corrente) and list of areas per
        textural class (ha).
    """
    soil_asset = ee.ImageCollection(_SOIL_TEXTURE_ASSET).toBands().select(['textural_group_000_030_v1_textural_group'])
    soil_asset = soil_asset.rename(['class'])

    areaImg = ee.Image.pixelArea().divide(10000).addBands(soil_asset)

    stats = areaImg.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName='class'),
        geometry=roi,
        scale=30,
        maxPixels=1e13
    )

    groups_info = stats.get('groups').getInfo()
    soil_data_list: List[SoilData] = []

    if groups_info:
        for group in groups_info:
            class_id = str(int(group['class']))
            class_name = _SOIL_TEXTURE_CLASSES.get(class_id, f"Classe {class_id}")
            area_value = round(float(group['sum']), 2)

            soil_data_list.append(SoilData(soil_class=class_name, amount=Value(value=area_value, unity="hectares")))

    return SoilStats(observation_year=datetime.date.today().year, data=soil_data_list)


def query_pasture_statistics(
    coords: List[List[List[List[float]]]],
    month: int,
    year: int,
    pasture_mask: Optional[ee.Image] = None,
    feature_key: Optional[str] = None,
) -> PropertyStats:
    """
    Extracts pasture statistics (biomass, age, vigor and land use/land cover).

    Args:
        coords: List of coordinates representing the farm MultiPolygon.
        month (int): Reference month (biomass accumulates the previous month).
        year (int): Reference year.
        pasture_mask (ee.Image, optional): Deprecated EE mask.
        feature_key (str, optional): Stable cache key for the property.

    Returns:
        PropertyStats: PastureStats object combining BiomassStats, AgeStats,
        VigorStats and LULCStats.

    Raises:
        RuntimeError: On processing, server, connection or unexpected failures
            (with a message ready to be relayed to the user).
    """
    try:
        roi = ee.Geometry.MultiPolygon(coords)

        biomass_stats = get_biomass(
            roi, month, year, pasture_mask=pasture_mask, feature_key=feature_key
        )
        # cada função clampa sozinha pro último ano publicado no respectivo asset MapBiomas
        # (não trava mais em 2024 — avança automaticamente quando a MapBiomas atualizar)
        age_stats = get_pasture_age(roi, year, month)
        vigor_stats = get_pasture_vigor(roi, year, month)
        lulc_stats = get_land_use_land_cover(roi, year, month)

        result = PastureStats(
            biomass_stats=biomass_stats,
            age_stats=age_stats,
            vigor_stats=vigor_stats,
            lulc_stats=lulc_stats
        )

        return result

    except ValueError:
        log_error(traceback.format_exc())
        raise RuntimeError(
            "Peça desculpas e informe que houve um erro.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except ee.EEException:
        log_error(traceback.format_exc())
        raise RuntimeError(
            "Peça desculpas e informe que houve uma falha de processamento.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except requests.exceptions.HTTPError:
        log_error(traceback.format_exc())
        raise RuntimeError(
            "Peça desculpas e informe que o servidor de imagens do satélite falhou.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except requests.exceptions.RequestException:
        log_error(traceback.format_exc())
        raise RuntimeError(
            "Peça desculpas e informe que houve um problema de conexão ao baixar o mapa de biomassa.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except Exception:
        log_error(traceback.format_exc())
        raise RuntimeError(
            "Peça desculpas e informe que houve um erro inesperado.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    

def query_topographic_stats(coords: List[List[List[List[float]]]]) -> TopographicStats:
    """
    Computes average topographic statistics for the property using Copernicus
    DEM GLO30 (mean elevation in meters and mean slope in degrees).

    Args:
        coords: List of coordinates representing the farm MultiPolygon.

    Returns:
        TopographicStats: Mean elevation (meters) and mean slope (degrees).
    """
    from domain.schemas.property_stats import Value

    roi = ee.Geometry.MultiPolygon(coords)
    
    #Buscar a coleção
    dem_col = ee.ImageCollection("COPERNICUS/DEM/GLO30").filterBounds(roi)
    
    #Pegar a projeção de uma imagem original para não perder a escala em metros
    proj = dem_col.first().projection()
    
    #Criar o mosaico e forçar a projeção correta
    demdata = dem_col.select('DEM').mosaic().setDefaultProjection(proj)
    
    # 4. Calcular o slope (agora ele entende a relação metros/metros)
    slope = ee.Terrain.slope(demdata)
    
    # Cálculo das estatísticas
    statsdem = demdata.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=roi,
        scale=30,
        maxPixels=1e13
    )
    
    statsslope = slope.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=roi,
        scale=30,
        maxPixels=1e13
    )

    #Converter o valor de elevacao e declividade
    dem_info = statsdem.getInfo()
    slope_info = statsslope.getInfo()
    res_elev = dem_info.get('DEM')
    res_slope = slope_info.get('slope')

    # Nunca cair pra 0 quando o GEE não retorna a chave (ex.: propriedade sem
    # cobertura no DEM) — 0m de altitude / 0° de declividade são valores
    # plausíveis de verdade, então um fallback silencioso pareceria um dado
    # real em vez de "sem dado disponível".
    if res_elev is None or res_slope is None:
        raise RuntimeError(
            f"O Earth Engine não retornou altitude/declividade pra essa propriedade "
            f"(DEM={res_elev}, slope={res_slope})."
        )

    #Retornar os valores de elevação e declividade
    return TopographicStats(
        elevation=Value(value=round(res_elev, 2), unity="metros"),
        slope=Value(value=round(res_slope, 2), unity="graus")
    )