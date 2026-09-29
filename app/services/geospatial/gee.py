import ee
import PIL
import datetime
import requests
import traceback

from io import BytesIO
from typing import List

from agno.utils.log import log_error

from app.services.geospatial.image import append_discrete_legend, append_continuous_colorbar
from app.services.geospatial.pasture_biomass import DRY_BIOMASS_FACTOR, _annual_biomass_image, _latest_gpw_year
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


def _draw_feature_boundaries(roi):
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


def _get_t2g_biomass_image(roi, month, year, day=1):
    UGPP_SCALE_FACTOR = 0.1

    # Apply a 7-day margin to the reference date, then select the full month
    # containing that shifted date (e.g. run on Oct 5 -> Sep 28 -> September).
    ref_date = datetime.date(year, month, day) - datetime.timedelta(days=7)
    target_year, target_month = ref_date.year, ref_date.month

    start_date = ee.Date.fromYMD(target_year, target_month, 1)
    end_date = start_date.advance(1, 'month')

    n_days = ee.Number(end_date.difference(start_date, 'day'))

    ugpp = ee.ImageCollection("projects/wri-lcl-time2graze/assets/ugpp_prod_10m_v1")
    ugpp_col = ugpp.filterBounds(roi).filterDate(start_date, end_date)

    # Máscara de pastagem no mesmo ano do período de biomassa pedido (não mais fixa em 2024) —
    # limitada ao último ano publicado pelo GPW, já que o asset não cobre anos futuros.
    mask_year = min(target_year, _latest_gpw_year())
    grassland_asset = ee.ImageCollection("projects/global-pasture-watch/assets/ggc-30m/v1-1/grassland_c")
    grassland_mask = grassland_asset.filterBounds(roi).filterDate(f'{mask_year}-01-01', f'{mask_year + 1}-01-01').first().gte(1)

    if ugpp_col.size().eq(0).getInfo():
        log_error(
            f"_get_t2g_biomass_image returned None: empty UGPP collection "
            f"for roi={roi}, month={month}, year={year}, day={day}"
        )
        return None

    grassland_image: ee.Image = ugpp_col.mean() \
        .multiply(ee.Image(n_days)).multiply(ee.Image(UGPP_SCALE_FACTOR)).multiply(DRY_BIOMASS_FACTOR) \
        .updateMask(grassland_mask).clip(roi).rename('tonC_hec')
    
    return grassland_image, target_year, target_month
    

def retrieve_t2g_biomass_image(coords: List[List[List[List[float]]]], month: int, year: int, day: int = 1) -> PIL.Image.Image | None:
    try:
        roi = ee.Geometry.MultiPolygon(coords)

        result = _get_t2g_biomass_image(roi, month, year, day)

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
        
        palette = ['#000033','#9400D3','#FF00FF','#00FFFF','#FFFFFF']
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
            title=f"Biomassa\n({str(_target_year)}/{str(_target_month)}) - T2G", 
            vmin=round(min_bio_val),
            vmax=round(max_bio_val),
            palette=palette
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


def retrieve_feature_soil_texture_image(coords: List[List[List[List[float]]]]):
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


def get_biomass(roi: ee.Geometry, year: int, month: int, day: int = 1) -> 'BiomassStats':
    result = _get_t2g_biomass_image(roi, month, year, day)

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


def get_pasture_age(roi: ee.Geometry, year: int, month: int = None) -> List['AgeStats']:
    # 30-40 = idade calculada com precisão nesse intervalo; ≥40 = pixel bateu no valor
    # sentinela do asset (pastagem já madura ao início da série, idade real desconhecida
    # e possivelmente bem maior que 40) — não misturamos as duas coisas na mesma classe.
    AGE_DICT = {'1':'1-10', '2':'10-20', '3':'20-30', '4':'30-40', '5':'≥40 (idade real indeterminada)'}

    target_year = min(year, _latest_asset_year(_AGE_ASSET))
    age_asset = ee.Image(_AGE_ASSET)
    raw_age = age_asset.select(target_year - 2000).subtract(200)
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

def get_pasture_vigor(roi: ee.Geometry, year: int, month: int = None) -> List['VigorStats']:
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

def get_land_use_land_cover(roi: ee.Geometry, year: int, month: int = None) -> List['LULCStats']:
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

    target_year = min(year, _latest_asset_year(_LULC_ASSET))
    class_asset = ee.Image(_LULC_ASSET)
    last_class = class_asset.select(target_year - 2000)

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

def query_pasture_statistics(coords: List[List[List[List[float]]]], year: int, month: int, day: int = 1) -> PropertyStats:
    """
    Extração de estatísticas de pastagem (biomassa, vigor, idade e chuva).
    """
    try:
        roi = ee.Geometry.MultiPolygon(coords)

        biomass_stats = get_biomass(roi, year, month, day)
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
    

def query_topographic_stats(coords: List[List[List[List[float]]]]):
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