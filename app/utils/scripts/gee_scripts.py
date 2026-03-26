import os
import ee
import PIL
import datetime
import requests
import geemap as gee

from io import BytesIO
from typing import List

from app.utils.scripts.image_scripts import add_legend
from app.utils.interfaces.ee_data_interfaces import PastureStatsResult
from app.utils.dummy_logger import error


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
    print(f"Authentication failed: {e}")


def retrieve_feature_images(coords: List[List[List[List[float]]]]) -> List[PIL.Image]:
    """
    Gera imagens de satélite individuais para cada polígono da propriedade rural.
    
    Args:
        coords: Lista de coordenadas representando o MultiPolygon da fazenda.
        
    Returns:
        List[PIL.Image]: Uma lista de imagens (PIL.Image) correspondentes a cada polígono.
    """
    try:
        # 1. Cria a geometria total para otimizar a busca da imagem base
        roi = ee.Geometry.MultiPolygon(coords)

        today = datetime.date.today()
        s_date = ee.Date.fromYMD(today.year - 1, today.month, 1)
        e_date = s_date.advance(1, 'year')

        # 2. Configura e processa a imagem base (feita apenas 1x para toda a fazenda)
        base_collection = (
            ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
            .filterBounds(roi)
            .filterDate(s_date, e_date)
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE',10))
            .median()
        )
        base_collection = base_collection.visualize(**{"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000})

        geometries = roi.geometries().getInfo()

        result_imgs = []

        # 3. Itera diretamente sobre a lista Python (evita o .getInfo() que custa tempo e rede)
        for geometry in geometries:
            # Instancia apenas o polígono atual
            feature = ee.Feature(geometry)

            # 4. Desenha o contorno
            empty = ee.Image().byte()
            outline = empty.paint(ee.FeatureCollection([feature]), 1, 3)
            outline = outline.updateMask(outline)
            outline_rgb = outline.visualize(**{"palette":['FF0000']})

            # 5. Mescla as imagens e recorta com a margem de 256m
            final_image = base_collection.blend(outline_rgb).clip(feature.buffer(256).bounds())

            # 6. Gera URL e faz download
            url = final_image.getThumbURL({"dimensions": 256,"format": "png"})

            response = requests.get(url, timeout=60)
            response.raise_for_status() # Levanta requests.exceptions.HTTPError em caso de falha HTTP

            # 7. Converte e armazena
            img_pil = PIL.Image.open(BytesIO(response.content))
            result_imgs.append(img_pil)

        return result_imgs
    
    except ee.EEException as e:
        raise RuntimeError(
            f"Falha ao processar as coordenadas no satélite. "
            f"Verifique se as coordenadas da área estão corretas. Detalhes: {str(e)}"
        )
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(
            f"O servidor de imagens do satélite retornou um erro. "
            f"Tente solicitar a imagem novamente em alguns instantes. Detalhes: {str(e)}"
        )
    except requests.exceptions.RequestException as e:
        raise RuntimeError(
            f"Não foi possível baixar a imagem por falha de conexão. "
            f"Pode haver instabilidade na rede. Detalhes: {str(e)}"
        )
    except PIL.UnidentifiedImageError as e:
        raise RuntimeError(
            f"O arquivo recebido do satélite está corrompido ou num formato inesperado. Detalhes: {str(e)}"
        )
    except Exception as e:
        raise RuntimeError(
            f"Ocorreu um erro inesperado ao gerar a imagem da fazenda. Detalhes: {str(e)}"
        )


# TODO: Otimizar e tornar mais legivel.
def retrieve_feature_biomass_image(coords: List[List[List[List[float]]]]) -> PIL.Image:
    """
    Gera uma imagem de satélite com a camada de biomassa de pastagem sobreposta,
    baseada na geometria da propriedade rural fornecida.
    
    Args:
        coords: Lista de coordenadas representando o MultiPolygon da fazenda.
        
    Returns:
        PIL.Image: Imagem final mesclada contendo satélite, biomassa, contorno e legenda.
    """
    try:
        # 1. Geometria e Datas
        roi = ee.Geometry.MultiPolygon(coords)

        today = datetime.date.today()
        s_date = ee.Date.fromYMD(today.year - 1, today.month, 1)
        e_date = s_date.advance(1, 'year')

        # 2. Imagem Base (Sentinel-2)
        base_collection = (
            ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
            .filterBounds(roi)
            .filterDate(s_date, e_date)
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE',10))
            .median()
        )
        base_collection = base_collection.visualize(**{"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}) 

        # 3. Camada de Biomassa (MapBiomas)
        biomass_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_biomass_v2')
        last_band_idx = biomass_asset.bandNames().size().subtract(1)
        biomass = biomass_asset.select([last_band_idx]).clip(roi)
        
        palette_biomass = ['#000033','#9400D3','#FF00FF','#00FFFF','#FFFFFF']
    
        # 4. Cálculo de Estatísticas (Otimização do getInfo)
        stats_biomass_ee = biomass.reduceRegion(
                reducer=ee.Reducer.minMax(),
                geometry=roi,
                scale=30,
                maxPixels=1e13
        )

        stats_dict = stats_biomass_ee.getInfo()

        # Busca as chaves dinamicamente (para não depender do nome exato da banda)
        min_key = next((k for k in stats_dict if k.endswith('_min')), None)
        max_key = next((k for k in stats_dict if k.endswith('_max')), None)

        if not min_key or stats_dict[min_key] is None:
            raise ValueError("Não foi possível calcular a biomassa. A área pode não conter pastagem mapeada.")

        min_bio_val = stats_dict[min_key]
        max_bio_val = stats_dict[max_key]    
        
        bioprop = biomass.visualize(**{"min": min_bio_val, "max": max_bio_val, "palette": palette_biomass})        
        
        # 6. Contorno da Propriedade
        empty = ee.Image().byte()
        outline = empty.paint(ee.FeatureCollection([ee.Feature(roi)]), 1, 3)
        outline = outline.updateMask(outline)
        outline_rgb = outline.visualize(**{"palette":['FF0000']})

        # 7. Unificação e Recorte (Buffer de 400m para contexto)
        final_image = base_collection.blend(bioprop.clip(roi))
        final_image = final_image.blend(outline_rgb).clip(roi.buffer(256).bounds());
        
        # 8. Geração de URL e Download (Resolução ajustada para 512)
        url = final_image.getThumbURL({"dimensions": 512,"format": "png"})
        
        resposta = requests.get(url, timeout=60)
        resposta.raise_for_status()
    
        # 9. Conversão PIL
        img = PIL.Image.open(BytesIO(resposta.content))

        # 10. Inserção da Legenda (Usando os valores que já temos em memória)
        img = add_legend(
            img, 
            title=f"Biomassa\npasto ({str(2024)})", 
            vmin=round(float(min_bio_val) * 0.09), # ton->pixel 
            vmax=round(float(max_bio_val) * 0.09), # ton->pixel
            palette=palette_biomass
        )

        return img

    except ValueError:
        raise RuntimeError(
            f"Peça desculpas e informe que houve um erro.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except ee.EEException:
        raise RuntimeError(
            f"Peça desculpas e informe que houve uma falha de processamento.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except requests.exceptions.HTTPError:
        raise RuntimeError(
            f"Peça desculpas e informe que o servidor de imagens do satélite falhou.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except requests.exceptions.RequestException:
        raise RuntimeError(
            f"Peça desculpas e informe que houve um problema de conexão ao baixar o mapa de biomassa.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except Exception:
        raise RuntimeError(
            f"Peça desculpas e informe que houve um erro inesperado.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    

# TODO: Otimizar e tornar mais legivel. (Talvez criar uma função para cada operação)
def ee_query_pasture(coords: List[List[List[List[float]]]]) -> PastureStatsResult:
    """
    Extração de estatísticas de pastagem (biomassa, vigor, idade e chuva).
    """
    from app.utils.interfaces.ee_data_interfaces import Value, BiomassData, AgeData, VigorData, LULCClassData

    try:
        roi = ee.Geometry.MultiPolygon(coords)

        # ==================== Query Biomass ====================
        biomass_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_biomass_v2')
        last_biomass = biomass_asset.select(biomass_asset.bandNames().size().subtract(1))
        
        stats = last_biomass.reduceRegion(
                    reducer=ee.Reducer.sum(),
                    geometry=roi,
                    scale=30,
                    maxPixels=1e13)

        biomass_data = BiomassData(amount=Value(value=stats.getInfo()['biomass_2024'] * 0.09, unity="tonelada(s) de matéria seca anual"))

        # ==================== Query Age ====================
        AGE_DICT = {'1':'1-10', '2':'10-20', '3':'20-30', '4':'30-40'}

        age_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_age_v2')
        last_age = age_asset.select(age_asset.bandNames().size().subtract(1))

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
        VIGOR_DICT = {'1':'Baixo', '2':'Médio', '3':'Alto'}

        vigor_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_vigor_v3')
        last_vigor = vigor_asset.select(vigor_asset.bandNames().size().subtract(1))

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
        last_class = class_asset.select(class_asset.bandNames().size().subtract(1))

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

        result = PastureStatsResult(
            biomass=biomass_data,
            age=age_data_list,
            vigor=vigor_data_list,
            lulc_class=lulc_class_data_list
            )

        return result
    
    except ValueError:
        raise RuntimeError(
            f"Peça desculpas e informe que houve um erro.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except ee.EEException:
        raise RuntimeError(
            f"Peça desculpas e informe que houve uma falha de processamento.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except requests.exceptions.HTTPError:
        raise RuntimeError(
            f"Peça desculpas e informe que o servidor de imagens do satélite falhou.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except requests.exceptions.RequestException:
        raise RuntimeError(
            f"Peça desculpas e informe que houve um problema de conexão ao baixar o mapa de biomassa.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )
    except Exception:
        raise RuntimeError(
            f"Peça desculpas e informe que houve um erro inesperado.\n"
            "Peça ao usuário que tente novamente mais tarde."
        )