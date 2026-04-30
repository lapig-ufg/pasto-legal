import os
import ee
import PIL
import datetime
import requests
import traceback

from io import BytesIO
from typing import List

from agno.utils.log import log_error

from app.utils.scripts.image_scripts import add_legend, add_legend_descriptor
from app.utils.interfaces.property_stats import PropertyStats, PastureStats, TopographicStats


_FEATURE_BUFFER = 256

_IMAGE_DIMENSION = 512


if not (GEE_SERVICE_ACCOUNT := os.environ.get('GEE_SERVICE_ACCOUNT')):
    raise ValueError("GEE_SERVICE_ACCOUNT environment variables must be set.")
if not (GEE_KEY_FILE := os.environ.get('GEE_KEY_FILE')):
    raise ValueError("GEE_KEY_FILE environment variables must be set.")
if not (GEE_PROJECT := os.environ.get('GEE_PROJECT')):
    raise ValueError("GEE_PROJECT environment variables must be set.")

try:
    credentials = ee.ServiceAccountCredentials(GEE_SERVICE_ACCOUNT, GEE_KEY_FILE)
    ee.Initialize(credentials, project=GEE_PROJECT)
    GEE_CONNECTED_FLAG = True
except Exception as e:
    log_error(f"Authentication failed: {e}")
    raise ValueError("GEE_PROJECT environment variables must be set.")


def _get_base_image(roi, year: int = None) -> PIL.Image:
    """
    Gera imagen de satélite para um polígono.
    
    Args:
        coords: Lista de coordenadas representando o MultiPolygon da fazenda.
        
    Returns:
        PIL.Image: Imagem final correspondente ao polígono.
    """


#    var s_date = ee.Date.fromYMD(2002 - 1, 12, 1)
#    var e_date = s_date.advance(1, 'year')
#
#    function applyScale(image) {
#    var opticalBands = image.select('SR_B.').multiply(0.0000275).add(-0.2);
#    return image.addBands(opticalBands, null, true);
#    }
#
#    var image_collection = ee.ImageCollection("LANDSAT/LE07/C02/T1_L2")
#    .filterBounds(geometry)
#    .filterDate(s_date, e_date)
#    .filter(ee.Filter.lt("CLOUD_COVER", 30))
#    .map(applyScale) // Aplica o fator de escala
#    .median();
#
#    // Agora o max deve ser em torno de 0.3 (refletância real)
#    var visParams = {"bands": ["SR_B3", "SR_B2", "SR_B1"], "min": 0, "max": 0.4};
#
#    var image = image_collection.visualize(visParams)
#
#    Map.addLayer(image)
#    Map.centerObject(geometry)


    try:
        if not year:
            date = datetime.date.today()
        else:
            date = datetime.date(year, 12, 31)  

        s_date = ee.Date.fromYMD(date.year - 1, date.month, 1)
        e_date = s_date.advance(1, 'year')

        if date.year >= 2016:
            asset = "COPERNICUS/S2_SR_HARMONIZED"
            filter_prop = "CLOUDY_PIXEL_PERCENTAGE"
            visualize_params = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}

        elif date.year >= 2013:
            asset = "LANDSAT/LC08/C02/T1_L2"
            filter_prop = "CLOUD_COVER"
            visualize_params = {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 0, "max": 1}

        elif date.year == 2012:
            asset = "LANDSAT/LE07/C02/T1_L2"
            filter_prop = "CLOUD_COVER"
            visualize_params = {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 0, "max": 1}

        elif date.year >= 2003:
            asset = "LANDSAT/LT05/C02/T1_L2"
            filter_prop = "CLOUD_COVER"
            visualize_params = {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 0, "max": 1}

        else:
            asset = "LANDSAT/LE07/C02/T1_L2"
            filter_prop = "CLOUD_COVER"
            visualize_params = {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 0, "max": 1}

        image_collection = (ee.ImageCollection(asset)
            .filterBounds(roi)
            .filterDate(s_date, e_date)
            .filter(ee.Filter.lt(filter_prop, 10))
            .median()
        )

        image = image_collection.visualize(**visualize_params)
        
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


def retrieve_feature_biomass_image(coords: List[List[List[List[float]]]], year: int = None) -> PIL.Image:
    """
    Gera uma imagem de satélite com a camada de biomassa de pastagem sobreposta,
    baseada na geometria da propriedade rural fornecida.
    
    Args:
        coords: Lista de coordenadas representando o MultiPolygon da fazenda.
        
    Returns:
        PIL.Image: Imagem final mesclada contendo satélite, biomassa, contorno e legenda.
    """
    try:
        biomass_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_biomass_v2')
        biomass_asset_bands = biomass_asset.bandNames().getInfo()

        max_year = int(biomass_asset_bands[-1].replace("biomass_", ""))
        min_year = int(biomass_asset_bands[0].replace("biomass_", ""))

        if year is None:
            year = max_year

        if year < min_year or year > max_year:
            raise ValueError(f"O ano deve estar entre {min_year} e {max_year}.")
        
        roi = ee.Geometry.MultiPolygon(coords)

        biomass = biomass_asset.select([year - 2000]).clip(roi)

        stats_biomass_ee = biomass.reduceRegion(
            reducer=ee.Reducer.minMax(),
            geometry=roi,
            scale=30,
            maxPixels=1e13
        )

        stats_dict = stats_biomass_ee.getInfo()

        min_key = next((k for k in stats_dict if k.endswith('_min')), None)
        max_key = next((k for k in stats_dict if k.endswith('_max')), None)

        if not min_key or stats_dict[min_key] is None:
            raise ValueError("Não foi possível calcular a biomassa. A área pode não conter pastagem mapeada.")

        min_bio_val = stats_dict[min_key]
        max_bio_val = stats_dict[max_key]    
        
        palette = ['#000033','#9400D3','#FF00FF','#00FFFF','#FFFFFF']
        bioprop = biomass.visualize(**{"min": min_bio_val, "max": max_bio_val, "palette": palette})        
        
        base_image = _get_base_image(roi=roi, year=year)

        outline = _draw_feature_boundaries(roi=roi)

        final_image = base_image.blend(bioprop.clip(roi))
        final_image = final_image.blend(outline).clip(roi.buffer(_FEATURE_BUFFER).bounds());
        
        url = final_image.getThumbURL({"dimensions":_IMAGE_DIMENSION, "format": "png"})
        
        resposta = requests.get(url, timeout=60)
        resposta.raise_for_status()
    
        img = PIL.Image.open(BytesIO(resposta.content))

        img = add_legend(
            img, 
            title=f"Biomassa\npasto ({str(2024)})", 
            vmin=round(float(min_bio_val) * 0.09), # ton->pixel 
            vmax=round(float(max_bio_val) * 0.09), # ton->pixel
            palette=palette
        )

        return img

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
        img_pil = add_legend_descriptor(img_pil,"Textura Solo", PALETTE)

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


def query_pasture_statistics(coords: List[List[List[List[float]]]], year: int) -> PropertyStats:
    """
    Extração de estatísticas de pastagem (biomassa, vigor, idade e chuva).
    """
    from app.utils.interfaces.property_stats import Value, BiomassData, AgeData, VigorData, LULCClassData

    try:
        biomass_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_biomass_v2')
        biomass_asset_bands = biomass_asset.bandNames().getInfo()

        max_year = int(biomass_asset_bands[-1].replace("biomass_", ""))
        min_year = int(biomass_asset_bands[0].replace("biomass_", ""))

        if year < min_year or year > max_year:
            raise ValueError(f"O ano deve estar entre {min_year} e {max_year}.")

        roi = ee.Geometry.MultiPolygon(coords)

        # ==================== Query Biomass ====================
        biomass_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_biomass_v2')
        last_biomass = biomass_asset.select(year - 2000)
        
        stats = last_biomass.reduceRegion(
                    reducer=ee.Reducer.sum(),
                    geometry=roi,
                    scale=30,
                    maxPixels=1e13)

        biomass_data = BiomassData(amount=Value(value=stats.getInfo()[f'biomass_{year}'] * 0.09, unity="tonelada(s) de matéria seca anual"))

        # ==================== Query Age ====================
        AGE_DICT = {'1':'1-10', '2':'10-20', '3':'20-30', '4':'30-40'}

        age_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_age_v2')
        last_age = age_asset.select(year - 2000)

        last_age = last_age.subtract(200)
        last_age = last_age.where(last_age.eq(-100), 40)
        last_age = (last_age.where(last_age.gte(1).And(last_age.lte(10)), 1)
                            .where(last_age.gt(10).And(last_age.lte(20)), 2)
                            .where(last_age.gt(20).And(last_age.lte(30)), 3)
                            .where(last_age.gt(30).And(last_age.lte(40)), 4)
                    ).rename('Anos');

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
                
                age_data = AgeData(age=class_name, amount=Value(value=area_value, unity="hectares (ha)"))
                age_data_list.append(age_data)

        # ==================== Query Vigor ====================
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
                
                vigor_data = VigorData(vigor=vigor_name, amount=Value(value=area_value, unity="hectares (ha)"))
                vigor_data_list.append(vigor_data)

        # ==================== Query Class ====================
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

        lulc_class_data_list: List[LULCClassData] = []

        if groups_info:
            for group in groups_info:
                class_id = str(int(group['class']))
                class_name = CLASSES.get(class_id)
                
                area_value = round(float(group['sum']), 2)
                
                class_data = LULCClassData(lulc_class=class_name, amount=Value(value=area_value, unity="hectares"))
                lulc_class_data_list.append(class_data)

        # ==================== Final Result ====================

        result = PastureStats(
            biomass=biomass_data,
            age=age_data_list,
            vigor=vigor_data_list,
            lulc_class=lulc_class_data_list,
            year=year
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
    from app.utils.interfaces.property_stats import Value

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