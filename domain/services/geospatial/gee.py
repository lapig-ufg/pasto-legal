import ee
import PIL
import datetime
import requests
import traceback

from io import BytesIO
from typing import List, Optional, Tuple

from PIL import ImageDraw, ImageFont
from shapely.geometry import shape as shapely_shape

from semente.logging import log_error, log_warning

from semente.configs.config import config

from domain.services.geospatial.image import append_discrete_legend, append_continuous_colorbar
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
    SoilStats,
    PastureStats
    )


_FEATURE_BUFFER = 256

_IMAGE_DIMENSION = 512

# Higher resolution used on the property confirmation image so that the
# paddock labels remain readable after WhatsApp compression.
_OVERVIEW_IMAGE_DIMENSION = 1024

_LABEL_FONT_PATH = "assets/fonts/DejaVuSans-Bold.ttf"

_HIGHVOLUME_URL = "https://earthengine-highvolume.googleapis.com"

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
    
    Args:
        coords: Lista de coordenadas representando o MultiPolygon da fazenda.
        
    Returns:
        List[PIL.Image]: Uma lista de imagens (PIL.Image) correspondentes a cada polígono.
    """
    try:
        result_imgs = []
        for _coords in coords:
            roi = ee.Geometry.MultiPolygon([_coords])

            base_image = _get_base_image(roi=roi)

            outline = _draw_feature_boundaries(roi=roi)

            final_image = base_image.blend(outline).clip(roi.buffer(_FEATURE_BUFFER).bounds())

            url = final_image.getThumbURL({"dimensions":_IMAGE_DIMENSION, "format":"png"})

            response = requests.get(url, timeout=60)
            response.raise_for_status()

            img_pil = PIL.Image.open(BytesIO(response.content))
            result_imgs.append(img_pil)

        return result_imgs
    
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


def retrieve_plain_satellite_image(coords: List[List[List[List[float]]]]) -> List[PIL.Image]:
    """
    Gera imagens de satélite individuais para cada polígono da propriedade rural,
    sem contorno ou qualquer sobreposição (imagem "crua").

    Args:
        coords: Lista de coordenadas representando o MultiPolygon da fazenda.

    Returns:
        List[PIL.Image]: Uma lista de imagens (PIL.Image) correspondentes a cada polígono.
    """
    try:
        result_imgs = []
        for _coords in coords:
            roi = ee.Geometry.MultiPolygon([_coords])

            base_image = _get_base_image(roi=roi)

            final_image = base_image.clip(roi.buffer(_FEATURE_BUFFER).bounds())

            url = final_image.getThumbURL({"dimensions": _IMAGE_DIMENSION, "format": "png"})

            response = requests.get(url, timeout=60)
            response.raise_for_status()

            img_pil = PIL.Image.open(BytesIO(response.content))
            result_imgs.append(img_pil)

        return result_imgs

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

        base_image = _get_base_image(roi=roi)

        if paddocks:
            features = [
                ee.Feature(ee.Geometry.MultiPolygon(coords))
                for coords, _label in paddocks
            ]
            outline = ee.Image().byte()
            outline = outline.paint(ee.FeatureCollection(features), 1, 3)
            outline = outline.updateMask(outline)
            outline = outline.visualize(**{"palette": ["FF0000"]})
        else:
            outline = _draw_feature_boundaries(roi=roi)

        region = roi.buffer(_FEATURE_BUFFER).bounds()
        final_image = base_image.blend(outline).clip(region)

        bounds_info = region.coordinates().getInfo()[0]
        west = min(coord[0] for coord in bounds_info)
        east = max(coord[0] for coord in bounds_info)
        south = min(coord[1] for coord in bounds_info)
        north = max(coord[1] for coord in bounds_info)

        span_lon = east - west
        span_lat = north - south
        if span_lon >= span_lat:
            width = dimension
            height = max(1, int(round(dimension * span_lat / span_lon)))
        else:
            height = dimension
            width = max(1, int(round(dimension * span_lon / span_lat)))

        url = final_image.getThumbURL(
            {"dimensions": f"{width}x{height}", "format": "png"}
        )

        response = requests.get(url, timeout=60)
        response.raise_for_status()

        img_pil = PIL.Image.open(BytesIO(response.content)).convert("RGB")

        if paddocks:
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
):
    """
    Computes the accumulated dry biomass image (ton/ha) from UGPP productivity.

    Uses the Time2Graze collection (10m UGPP) accumulated over the given period,
    multiplied by the scale factor, LUEmax, the IPCC factor (C -> dry biomass) and
    the ton/ha conversion factor, masked by Global Pasture Watch grassland areas.

    Args:
        roi (ee.Geometry): Region of interest (farm polygon).
        start_year (int): Start year of the accumulation period.
        start_month (int): Start month of the accumulation period.
        start_day (int): Start day of the accumulation period.
        end_year (int): End year (exclusive) of the accumulation period.
        end_month (int): End month (exclusive) of the accumulation period.
        end_day (int): End day (exclusive) of the accumulation period.

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
    mask_year = min(start_year, _latest_gpw_year())
    grassland_asset = ee.ImageCollection("projects/global-pasture-watch/assets/ggc-30m/v1-1/grassland_c")
    grassland_mask = grassland_asset.filterBounds(roi).filterDate(f'{mask_year}-01-01', f'{mask_year + 1}-01-01').first().gte(1)

    if ugpp_col.size().eq(0).getInfo():
        log_error(
            f"_get_t2g_biomass_image returned None: empty UGPP collection "
            f"for roi={roi}, period={start_year}/{start_month}/{start_day} - {end_year}/{end_month}/{end_day}"
        )
        return None

    grassland_image: ee.Image = ugpp_col.mean() \
        .multiply(ee.Image(n_days)).multiply(ee.Image(UGPP_SCALE_FACTOR)).multiply(DRY_BIOMASS_FACTOR) \
        .updateMask(grassland_mask).clip(roi).rename('tonC_hec')
    
    return grassland_image, start_year, start_month
    

def retrieve_t2g_biomass_image(coords: List[List[List[List[float]]]], month: int, year: int) -> tuple[PIL.Image.Image, int, int] | None:
    """
    Generates a satellite image with the T2G (Time2Graze) biomass layer overlaid,
    relative to the reference month (the month before the one given), with a colorbar.

    Args:
        coords: List of coordinates representing the farm MultiPolygon.
        month (int): Reference month (the accumulation uses the previous month).
        year (int): Reference year.

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

        start_date, end_date = _reference_period(year, month)
        result = _get_t2g_biomass_image(
            roi,
            start_date.year, start_date.month, start_date.day,
            end_date.year, end_date.month, end_date.day
        )

        if result is None:
            fallback_month, fallback_year = (12, year - 1) if month == 1 else (month - 1, year)
            log_warning(
                f"retrieve_t2g_biomass_image: no UGPP data for reference period of {month}/{year}; "
                f"falling back to previous month {fallback_month}/{fallback_year}"
            )
            start_date, end_date = _reference_period(fallback_year, fallback_month)
            result = _get_t2g_biomass_image(
                roi,
                start_date.year, start_date.month, start_date.day,
                end_date.year, end_date.month, end_date.day
            )

            if result is None:
                return None

        biomass_img, _target_year, _target_month = result
        
        stats = biomass_img.reduceRegion(
                reducer=ee.Reducer.minMax(),
                geometry=roi,
                scale=10,
                maxPixels=1e13
            ).getInfo()

        min_key = next((k for k in stats if k.endswith('_min')), None)
        max_key = next((k for k in stats if k.endswith('_max')), None)

        if not min_key or stats[min_key] is None:
            raise ValueError("Não foi possível calcular a biomassa. A área pode não conter pastagem mapeada.")

        min_bio_val = stats[min_key]
        max_bio_val = stats[max_key]    
        
        palette = ["#f75639", "#eef79c", "#f5d570", "#8aa637", "#0b391f"]
        bioprop = biomass_img.visualize(**{"min": min_bio_val, "max": max_bio_val, "palette": palette})        
        
        base_image = _get_base_image(roi=roi, year=year)

        outline = _draw_feature_boundaries(roi=roi)

        final_image = base_image.blend(bioprop.clip(roi))
        final_image = final_image.blend(outline).clip(roi.buffer(_FEATURE_BUFFER).bounds());
        
        url = final_image.getThumbURL({"dimensions":_IMAGE_DIMENSION, "format": "png"})
        
        resposta = requests.get(url, timeout=60)
        resposta.raise_for_status()

        img = PIL.Image.open(BytesIO(resposta.content))

        img = append_continuous_colorbar(
            img, 
            title=f"Biomassa ({str(_target_year)}/{str(_target_month)}) - T2G", 
            vmin=round(min_bio_val, 1),
            vmax=round(max_bio_val, 1),
            unit="ton/ha",
            palette=palette,
            ndigits=1
        )

        return img, _target_year, _target_month

    except ValueError as error:
        log_error(traceback.format_exc())
        raise error
    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Peça desculpas e informe que houve uma falha de processamento.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except requests.exceptions.HTTPError as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Peça desculpas e informe que o servidor de imagens do satélite falhou.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except requests.exceptions.RequestException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Peça desculpas e informe que houve um problema de conexão ao baixar o mapa de biomassa.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Peça desculpas e informe que houve um erro inesperado.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )

def retrieve_gpw_biomass_image(coords: List[List[List[List[float]]]], year: int = None) -> PIL.Image.Image:
    """
    Mapa de biomassa seca de pastagem (Global Pasture Watch), usado como fallback
    quando o T2G não cobre a propriedade (fora da lista fixa de tiles) — cobertura
    nacional/global, sem essa limitação. Se `year` for omitido, usa o ano mais
    recente disponível no GPW.
    """
    roi = ee.Geometry.MultiPolygon(coords)

    if year is None:
        year = _latest_gpw_year()

    grassland_image = _annual_biomass_image(roi, year)

    stats = grassland_image.reduceRegion(
        reducer=ee.Reducer.minMax(),
        geometry=roi,
        scale=10,
        maxPixels=1e13
    ).getInfo()

    min_key = next((k for k in stats if k.endswith('_min')), None)
    max_key = next((k for k in stats if k.endswith('_max')), None)

    if not min_key or stats[min_key] is None:
        raise ValueError("Não foi possível calcular a biomassa. A área pode não conter pastagem mapeada.")

    min_bio_val = stats[min_key]
    max_bio_val = stats[max_key]

    palette = ['#000033', '#9400D3', '#FF00FF', '#00FFFF', '#FFFFFF']
    bioprop = grassland_image.visualize(**{"min": min_bio_val, "max": max_bio_val, "palette": palette})

    base_image = _get_base_image(roi=roi, year=year)

    outline = _draw_feature_boundaries(roi=roi)

    final_image = base_image.blend(bioprop.clip(roi))
    final_image = final_image.blend(outline).clip(roi.buffer(_FEATURE_BUFFER).bounds())

    url = final_image.getThumbURL({"dimensions": _IMAGE_DIMENSION, "format": "png"})

    resposta = requests.get(url, timeout=60)
    resposta.raise_for_status()

    img = PIL.Image.open(BytesIO(resposta.content))

    img = append_continuous_colorbar(
        img,
        title=f"Biomassa\n({str(year)}) - GPW",
        vmin=round(min_bio_val),
        vmax=round(max_bio_val),
        palette=palette
    )

    return img


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


def retrieve_t2g_biomass_video(
    coords: List[List[List[List[float]]]],
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
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

        roi = ee.Geometry.MultiPolygon(coords)

        frames: list[tuple[int, ee.Image, int, int]] = []
        global_min: float | None = None
        global_max: float | None = None

        for ref_year, ref_month in months:
            start_date, end_date = _reference_period(ref_year, ref_month)
            result = _get_t2g_biomass_image(
                roi,
                start_date.year, start_date.month, start_date.day,
                end_date.year, end_date.month, end_date.day
            )

            if result is None:
                log_warning(
                    f"retrieve_t2g_biomass_video: sem dados UGPP para {ref_month}/{ref_year}; frame ignorado"
                )
                continue

            biomass_img, _target_year, _target_month = result

            stats = biomass_img.reduceRegion(
                reducer=ee.Reducer.minMax(),
                geometry=roi,
                scale=10,
                maxPixels=1e13
            ).getInfo()

            min_key = next((k for k in stats if k.endswith('_min')), None)
            max_key = next((k for k in stats if k.endswith('_max')), None)

            if not min_key or stats[min_key] is None or stats[max_key] is None:
                log_warning(
                    f"retrieve_t2g_biomass_video: estatísticas vazias para {ref_month}/{ref_year}; frame ignorado"
                )
                continue

            frame_min = float(stats[min_key])
            frame_max = float(stats[max_key])
            global_min = frame_min if global_min is None else min(global_min, frame_min)
            global_max = frame_max if global_max is None else max(global_max, frame_max)

            frames.append((ref_year, biomass_img, start_date.year, start_date.month))

        if len(frames) < 2:
            log_warning(
                f"retrieve_t2g_biomass_video: apenas {len(frames)} frame(s) com dados UGPP "
                f"para o período {effective_start} - {effective_end}; retornando None"
            )
            return None

        frame_months: list[tuple[int, int]] = [(acc_year, acc_month) for _, _, acc_year, acc_month in frames]

        outline = _draw_feature_boundaries(roi=roi)
        frame_region = roi.buffer(_FEATURE_BUFFER).bounds()

        base_by_year: dict[int, ee.Image] = {
            year: _get_base_image(roi=roi, year=year) for year in {year for year, _, _, _ in frames}
        }

        visualized = []
        for year, frame, _acc_year, _acc_month in frames:
            bioprop = frame.visualize(
                **{"min": global_min, "max": global_max, "palette": BIOMASS_VIDEO_PALETTE}
            )
            composed = base_by_year[year].blend(bioprop.clip(roi)).blend(outline).clip(frame_region)
            visualized.append(composed)

        video_collection = ee.ImageCollection.fromImages(visualized)

        url = video_collection.getVideoThumbURL({
            "dimensions": _IMAGE_DIMENSION,
            "region": frame_region,
            "framesPerSecond": 2,
            "format": "gif",
        })

        response = requests.get(url, timeout=120)
        response.raise_for_status()

        return response.content, effective_start, effective_end, frame_months, global_min, global_max

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

def retrieve_feature_soil_texture_image(coords: List[List[List[List[float]]]]) -> PIL.Image.Image:
    """
    Generates a satellite image with the soil texture layer (0-30cm, MapBiomas
    Collection 3) overlaid, with a discrete legend of the texture classes.

    Args:
        coords: List of coordinates representing the farm MultiPolygon.

    Returns:
        PIL.Image: Final blended image containing satellite, soil texture,
        outline and legend.

    Raises:
        RuntimeError: On Earth Engine processing, image server, connection,
            image format or unexpected failures.
    """
    try:
        PALETTE = {
            'Afloramento':'#707070',
            'Muito Argiloso':'#a83800',
            'Argila':'#aa8686',
            'Siltoso':'#298289',
            'Arenoso':'#fffe73',
            'Médio':'#d7c5a5', 
        }

        roi = ee.Geometry.MultiPolygon(coords)
        
        soil_texture_asset = ee.ImageCollection("projects/mapbiomas-public/assets/brazil/soil/collection3/mapbiomas_brazil_collection3_soil_textural_group_v1")
        soil_texture = soil_texture_asset.toBands().select(['textural_group_000_030_v1_textural_group'])
        soil_texture = soil_texture.rename(['0-30cm'])

        palette = ['#707070','#a83800','#aa8686','#298289','#fffe73','#d7c5a5']
        final = soil_texture.visualize(**{"min": 1, "max": 6, "palette": palette}) 
        
        base_image = _get_base_image(roi=roi)

        outline = _draw_feature_boundaries(roi=roi)

        final_image = base_image.blend(final.clip(roi))
        final_image = final_image.blend(outline).clip(roi.buffer(_FEATURE_BUFFER).bounds());
            
        url = final_image.getThumbURL({"dimensions": _IMAGE_DIMENSION, "format": "png"})
            
        resposta = requests.get(url, timeout=60)
        resposta.raise_for_status()
        
        img_pil = PIL.Image.open(BytesIO(resposta.content)) 
        img_pil = append_discrete_legend(img_pil,"Textura Solo", PALETTE)

        return img_pil
    
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


def retrieve_pasture_vigor_image(coords: List[List[List[List[float]]]], year: int = 2024) -> PIL.Image:
    """
    Gera uma imagem de satélite com a camada de vigor de pastagem sobreposta,
    baseada na geometria da propriedade rural fornecida.

    Args:
        coords: Lista de coordenadas representando o MultiPolygon da fazenda.
        year (int, optional): Ano do mapeamento (MapBiomas). Usa 2024 se omitido.

    Returns:
        PIL.Image: Imagem final mesclada contendo satélite, vigor, contorno e legenda.
    """
    try:
        PALETTE = {
            'Baixo': '#d7191c',
            'Médio': '#fdae61',
            'Alto': '#1a9641',
        }

        roi = ee.Geometry.MultiPolygon(coords)

        vigor_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_vigor_v3')
        vigor = vigor_asset.select(year - 2000)

        palette = ['#d7191c', '#fdae61', '#1a9641']
        final = vigor.visualize(**{"min": 1, "max": 3, "palette": palette})

        base_image = _get_base_image(roi=roi)

        outline = _draw_feature_boundaries(roi=roi)

        final_image = base_image.blend(final.clip(roi))
        final_image = final_image.blend(outline).clip(roi.buffer(_FEATURE_BUFFER).bounds())

        url = final_image.getThumbURL({"dimensions": _IMAGE_DIMENSION, "format": "png"})

        response = requests.get(url, timeout=60)
        response.raise_for_status()

        img_pil = PIL.Image.open(BytesIO(response.content))
        img_pil = append_discrete_legend(img_pil, "Vigor da Pastagem", PALETTE)

        return img_pil

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


def get_biomass(roi: ee.Geometry, month: int, year: int) -> BiomassStats:
    """
    Computes pasture dry biomass accumulated in the reference month (the month
    before the one given), using the Time2Graze collection (10m UGPP).

    When there is no UGPP data for the period/region, falls back to the MapBiomas
    asset (2024 annual biomass, 0.09 scale, value accumulated over the year).

    Args:
        roi (ee.Geometry): Region of interest (farm polygon).
        month (int): Reference month (the accumulation uses the previous month).
        year (int): Reference year.

    Returns:
        BiomassStats: Observation year and accumulated value with unit
        ("tonelada(s) de matéria seca acumulada no mês ..." or "... no ano").
    """
    start_date, end_date = _reference_period(year, month)
    result = _get_t2g_biomass_image(
        roi,
        start_date.year, start_date.month, start_date.day,
        end_date.year, end_date.month, end_date.day
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

        month_dict = { 1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro" }

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


def query_pasture_statistics(coords: List[List[List[List[float]]]], month: int, year: int) -> PropertyStats:
    """
    Extracts pasture statistics (biomass, age, vigor and land use/land cover).

    Args:
        coords: List of coordinates representing the farm MultiPolygon.
        month (int): Reference month (biomass accumulates the previous month).
        year (int): Reference year.

    Returns:
        PropertyStats: PastureStats object combining BiomassStats, AgeStats,
        VigorStats and LULCStats.

    Raises:
        RuntimeError: On processing, server, connection or unexpected failures
            (with a message ready to be relayed to the user).
    """
    try:
        roi = ee.Geometry.MultiPolygon(coords)

        biomass_stats = get_biomass(roi, month, year)
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

    except ValueError as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Peça desculpas e informe que houve um erro.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except ee.EEException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Peça desculpas e informe que houve uma falha de processamento.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except requests.exceptions.HTTPError as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Peça desculpas e informe que o servidor de imagens do satélite falhou.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except requests.exceptions.RequestException as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Peça desculpas e informe que houve um problema de conexão ao baixar o mapa de biomassa.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except Exception as error:
        log_error(traceback.format_exc())
        raise RuntimeError(
            f"Peça desculpas e informe que houve um erro inesperado.\n"
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