import ee
import PIL
import datetime
import requests
import traceback

from io import BytesIO
from typing import List, Optional, Tuple

from PIL import ImageDraw, ImageFont
from shapely.geometry import shape as shapely_shape

from agno.utils.log import log_error, log_warning

from app.services.geospatial.image import append_discrete_legend
from app.schemas.property_stats import PropertyStats, PastureStats, TopographicStats
from app.schemas.property_stats import (
    Value, 
    BiomassStats,
    AgeData,
    AgeStats,
    VigorData,
    VigorStats,
    LULCData,
    LULCStats,
    PastureStats
    )
from app.configs.config import config


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


# As funções de mapa, vídeo e estatística de biomassa foram movidas para o pacote
# `app.services.geospatial.biomass`, que separa produtividade mensal, produtividade
# anual, biomassa em pé e forragem disponível em métricas distintas, com unidade,
# período, resolução efetiva, cobertura válida e incerteza explícitos, e que trata
# cada asset uGPP com o seu próprio contrato de escala (ugpp_cf_10m_v1 e
# ugpp_prod_10m_v1 armazenam valores em escalas diferentes).


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
    Produtividade de matéria seca da pastagem, como `BiomassStats` legado.

    Delega para `app.services.geospatial.biomass`, que separa produtividade
    mensal (t MS/ha/mês) de produtividade anual (t MS/ha/ano) e devolve a métrica
    com o seu período e a sua unidade explícitos. Quando não há dado mensal para
    a propriedade, cai para a série anual do MapBiomas — e a unidade devolvida diz
    que a métrica mudou, em vez de apresentar o valor anual como se fosse mensal.

    Prefira consumir `BiomassEstimate` diretamente (via
    `estimate_monthly_productivity` / `estimate_annual_productivity`): este wrapper
    existe apenas para os consumidores que ainda esperam o schema antigo, e ele
    perde os metadados de incerteza, cobertura válida e máscara.

    Args:
        roi (ee.Geometry): Região de interesse (polígono do imóvel).
        month (int): Mês de referência.
        year (int): Ano de referência.

    Returns:
        BiomassStats: Ano de observação e valor por hectare com a unidade da métrica
        efetivamente usada.
    """
    from app.services.geospatial.biomass.biomass_productivity import (
        estimate_annual_productivity,
        latest_monthly_productivity,
    )
    from app.services.geospatial.biomass.pasture_mask import build_pasture_mask

    reference = datetime.date(year, month, 1)
    mask = build_pasture_mask(roi=roi, strategy="official")

    estimate = latest_monthly_productivity(roi=roi, mask=mask, today=reference)

    if estimate is None:
        log_warning(
            "get_biomass: sem produtividade mensal para esta propriedade; "
            "usando a produtividade ANUAL do MapBiomas (outra métrica)."
        )
        estimate = estimate_annual_productivity(roi=roi)

    return BiomassStats(
        observation_year=estimate.period_start.year,
        amount=Value(value=round(estimate.value_per_ha, 2), unity=estimate.unit_label),
    )



def get_pasture_age(roi: ee.Geometry, year: int, month: int = None) -> AgeStats:
    """
    Computes pasture area (ha) per age class via MapBiomas (Collection 10).

    Raw ages are reclassified into 4 ranges: 1-10, 10-20, 20-30 and 30-40 years.

    Args:
        roi (ee.Geometry): Region of interest (farm polygon).
        year (int): Reference year of the mapping (band `year - 2000`).
        month (int, optional): Ignored; kept for signature compatibility.

    Returns:
        AgeStats: Observation year and list of areas per age range (ha).
    """
    AGE_DICT = {'1':'1-10', '2':'10-20', '3':'20-30', '4':'30-40'}

    age_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_age_v2')
    last_age = age_asset.select(year - 2000)

    last_age = last_age.subtract(200)
    last_age = last_age.where(last_age.eq(-100), 40)
    last_age = (last_age.where(last_age.gte(1).And(last_age.lte(10)), 1)
                        .where(last_age.gt(10).And(last_age.lte(20)), 2)
                        .where(last_age.gt(20).And(last_age.lte(30)), 3)
                        .where(last_age.gt(30).And(last_age.lte(40)), 4)
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

    return AgeStats(observation_year=2024, data=age_data_list)

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

    vigor_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_vigor_v3')
    last_vigor = vigor_asset.select(year - 2000)

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

    return VigorStats(observation_year=2024, data=vigor_data_list)

def get_land_use_land_cover(roi: ee.Geometry, year: int, month: int = None) -> LULCStats:
    """
    Computes area (ha) per land use and land cover class via MapBiomas
    (Collection 10, annual integration).

    Args:
        roi (ee.Geometry): Region of interest (farm polygon).
        year (int): Reference year of the mapping (band `year - 2000`).
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

    class_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_integration_v2')
    last_class = class_asset.select(year - 2000)

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

    return LULCStats(observation_year=2024, data=lulc_class_data_list)

def query_pasture_statistics(
    coords: List[List[List[List[float]]]],
    month: int,
    year: int,
    include_biomass: bool = True,
) -> PropertyStats:
    """
    Extracts pasture statistics (biomass, age, vigor and land use/land cover).

    Args:
        coords: List of coordinates representing the farm MultiPolygon.
        month (int): Mês de referência.
        year (int): Ano de referência.
        include_biomass (bool): Se False, omite `biomass_stats` — use quando as
            métricas de biomassa já vierem de `assess_property_biomass`, que as
            entrega separadas por conceito e com metadados completos, para não
            recalcular a mesma coisa duas vezes.

    Returns:
        PropertyStats: PastureStats object combining BiomassStats, AgeStats,
        VigorStats and LULCStats.

    Raises:
        RuntimeError: On processing, server, connection or unexpected failures
            (with a message ready to be relayed to the user).
    """
    try:
        roi = ee.Geometry.MultiPolygon(coords)

        biomass_stats = get_biomass(roi, month, year) if include_biomass else None
        age_stats = get_pasture_age(roi, 2024, month)
        vigor_stats = get_pasture_vigor(roi, 2024, month)
        lulc_stats = get_land_use_land_cover(roi, 2024, month)

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
    from app.schemas.property_stats import Value

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
    res_elev = statsdem.getInfo().get('DEM', 0)
    res_slope = statsslope.getInfo().get('slope', 0)

    #Retornar os valores de elevação e declividade
    return TopographicStats(
        elevation=Value(value=round(res_elev, 2), unity="metros"),
        slope=Value(value=round(res_slope, 2), unity="graus")
    )