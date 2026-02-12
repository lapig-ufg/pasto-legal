import os
import ee
import PIL
import datetime
import requests
import textwrap
import geemap as gee

from io import BytesIO
from pydantic import BaseModel

from app.utils.scripts.image_scripts import add_legend
from app.utils.exceptions.message_exception import MessageException


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


CLASSES = {
    'class':{
        '3':'Formação Florestal',
        '4':'Formação Savânica',
        '5':'Mangue',
        '6':'Floresta Alagável',
        '9':'Silvicultura',
        '11':'Campo Alagado e Área Pantanosa',
        '12':'Formação Campestre',
        '15':'Pastagem',
        '19':'Lavoura Temporária',
        '20':'Cana', 
        '29':'Afloramento Rochoso',        
        '39':'Soja',
        '32':'Apicum',
        '35':'Dendê', 
        '36':'Lavoura Perene',
        '40':'Arroz',
        '41':'Outras Lavouras Temporárias',
        '46':'Café',
        '47':'Citrus',
        '48':'Outras Lavouras Perenes',
        '49':'Restinga Arbórea',
        '50':'Restinga Herbácea',
        '62':'Algodão',
        '21':'Mosaico de Usos',
        '23':'Praia, Duna e Areal',
        '24':'Área Urbanizada',
        '30':'Mineração',
        '75':'Usina Fotovoltaica (beta)',
        '25':'Outras Áreas não Vegetadas',
        '26':"Corpo D'água",
        '33':'Rio, Lago e Oceano',
        '31':'Aquicultura',
        '27':'Não observado'
    },
    'vigor':{
        '1':'Baixo',
        '2':'Médio',
        '3':'Alto',
    },
    'age':{
        '1':'1-10', 
        '2':'10-20', 
        '3':'20-30', 
        '4':'30-40', 
    }
}


# TODO: Otimizar e tornar mais legivel.
def retrieve_feature_images(geo_json: dict) -> list[PIL.Image]:
    """
    Gera uma imagem de satélite da propriedade rural baseada nos dados do CAR do usuário
    armazenados na sessão. Esta função não requer parâmetros, pois recupera 
    automaticamente a geometria da fazenda do estado atual da conversa.
    """
    # TODO: Será que da pra mudar para ee.Geometry.MultiPolygon? Se for possivel remover geemap da lista de bibliotecas do uv.
    roi = gee.geojson_to_ee(geo_json)
    rows = roi.aggregate_array('codigo').getInfo()

    sDate = ee.Date.fromYMD(datetime.date.today().year - 1, datetime.date.today().month, 1)
    eDate= sDate.advance(1, 'year')

    sentinel = (
        ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(roi)
        .filterDate(sDate, eDate)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE',10))
        .median()
    )

    sentinel = sentinel.visualize(**{"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000})

    try:
        result = []

        for idx, row in enumerate(rows, 1):
            empty = ee.Image().byte()

            feat = roi.filter(ee.Filter.eq('codigo', row))

            outline = empty.paint(ee.FeatureCollection([ee.Feature(feat.geometry())]), 1, 3)
            outline = outline.updateMask(outline)
            outline_rgb = outline.visualize(**{"palette":['FF0000']})

            # Unificando os dados
            final_image = sentinel.blend(outline_rgb).clip(feat.geometry().buffer(400).bounds())

            # Gerando a url
            url = final_image.getThumbURL({"dimensions": 256,"format": "png"})

            # 5. Download
            resposta = requests.get(url, timeout=60)
            resposta.raise_for_status()
        
            # 6. Converter para PIL.Image
            img_pil = PIL.Image.open(BytesIO(resposta.content))

            result.append(img_pil)

        return result
    # TODO: Mapear possíveis erros.
    except Exception as e:
        # TODO: Melhorar a menssagem de erro. Com motivo do erro e instrução de execução.
        raise Exception(f"Erro ao gerar imagem: {str(e)}")


# TODO: Otimizar e tornar mais legivel.
def retrieve_feature_biomass_image(coordinates: list) -> PIL.Image:
    """
    Gera uma imagem de satélite da propriedade rural baseada nos dados do CAR do usuário
    armazenados na sessão. Esta função não requer parâmetros, pois recupera 
    automaticamente a geometria da fazenda do estado atual da conversa.
    """
    roi = ee.Geometry.Polygon(coordinates)

    sDate = ee.Date.fromYMD(datetime.date.today().year - 1, datetime.date.today().month, 1)
    eDate= sDate.advance(1, 'year')

    sentinel = (
        ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(roi)
        .filterDate(sDate, eDate)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE',10))
        .median()
    )

    sentinel = sentinel.visualize(**{"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}) 

    #Coletando informações de biomassa
    biomass = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_biomass_v2')
    biomass = biomass.select(biomass.bandNames().size().subtract(1)).clip(roi)  
    
    #Paleta de cores na biomassa
    paletteBiomassa = ['#000033','#9400D3','#FF00FF','#00FFFF','#FFFFFF']
    
    try:
        empty = ee.Image().byte()

        #Agregando informação de biomassa
        statsbiomass = biomass.reduceRegion(
                reducer=ee.Reducer.minMax(),
                geometry=roi,
                scale=30,
                maxPixels=1e13
        )

        #Valor maximo e minimo da biomassa
        minBio = statsbiomass.get(ee.String(biomass.bandNames().get(0)).cat('_min'))
        maxBio = statsbiomass.get(ee.String(biomass.bandNames().get(0)).cat('_max'))               
        
        bioprop = biomass.visualize(**{"min": minBio, "max": maxBio,"palette": paletteBiomassa})        
        
        outline = empty.paint(ee.FeatureCollection([ee.Feature(roi)]), 1, 3)
        outline = outline.updateMask(outline)
        outline_rgb = outline.visualize(**{"palette":['FF0000']})

        # Unificando os dados
        final_image = sentinel.blend(bioprop.clip(roi))
        final_image = final_image.blend(outline_rgb).clip(roi.buffer(400).bounds());
        
        # Gerando a url
        url = final_image.getThumbURL({"dimensions": 256,"format": "png"})
        
        # Download
        resposta = requests.get(url, timeout=60)
        resposta.raise_for_status()
    
        # Converter para PIL.Image
        img = PIL.Image.open(BytesIO(resposta.content))

        # Inserção da Legenda: Usamos os valores capturados do GEE
        img = add_legend(
            img, 
            title=f"Biomassa\npasto ({str(2024)})", 
            vmin=round(float(minBio.getInfo()) * 0.09), # ton->pixel 
            vmax=round(float(maxBio.getInfo()) * 0.09), # ton->pixel
            palette=paletteBiomassa
        )

        return img
    # TODO: Mapear possíveis erros.
    except Exception as e:
        # TODO: Melhorar a menssagem de erro. Com motivo do erro e instrução de execução.
        raise Exception(f"Erro ao gerar imagem: {str(e)}")


def ee_query_biomass(roi: ee.Geometry.Polygon):
    biomass_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_biomass_v2')
    selectedBand = biomass_asset.bandNames().size().subtract(1)

    last = biomass_asset.select(selectedBand)
    
    stats = last.reduceRegion(
                  reducer=ee.Reducer.sum(),
                  geometry=roi,
                  scale=30,
                  maxPixels=1e13)

    return dict({'biomass': stats.getInfo()}) # ton->pixel 


def ee_query_age(roi: ee.Geometry.Polygon):
    age_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_age_v2')
    selectedBand = age_asset.bandNames().size().subtract(1)

    last = age_asset.select(selectedBand)
    last = last.subtract(200)
    last = last.where(last.eq(-100), 40)

    #Agrupando as informações para 04 classe
    last = (last.where(last.gte(1).And(last.lte(10)),1)
                        .where(last.gt(10).And(last.lte(20)),2)
                        .where(last.gt(20).And(last.lte(30)),3)
                        .where(last.gt(30).And(last.lte(40)),4)
                   ).rename('Anos');

    #Cálculo das áreas
    areaImg = ee.Image.pixelArea().divide(10000).addBands(last)

    #Agregando dados
    stats = areaImg.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName='class'),
        geometry=roi,
        scale=30,
        maxPixels=1e13
    )
    groups = ee.List(stats.get('groups'));

    #Template 
    initialDict = ee.Dictionary()
    
    # Iterar para calcular porcentagens e nomear classes
    yearDict = ee.Dictionary(groups.iterate(
          lambda group, d: ee.Dictionary(d).set(
              ee.Dictionary(CLASSES.get('age')).get(ee.String(ee.Number(ee.Dictionary(group).get('class')).toInt())),
              ee.Number(ee.Dictionary(group).get('sum')).format('%.2f')
          ), initialDict
    ))
    
    return dict({'age': yearDict.getInfo()})


def ee_query_vigor(roi: ee.Geometry.Polygon):
    vigor_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_vigor_v3')
    selectedBand = vigor_asset.bandNames().size().subtract(1)

    last = vigor_asset.select(selectedBand)

    areaImg = ee.Image.pixelArea().divide(10000).addBands(last)

    stats = areaImg.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName='class'),
        geometry=roi,
        scale=30,
        maxPixels=1e13
    )
    groups = ee.List(stats.get('groups'));

    initialDict = ee.Dictionary();

    yearDict = ee.Dictionary(groups.iterate(
        lambda group, d: ee.Dictionary(d).set(
            ee.Dictionary(CLASSES.get('vigor')).get(ee.String(ee.Number(ee.Dictionary(group).get('class')).toInt())),
            ee.Number(ee.Dictionary(group).get('sum')).format('%.2f')
        ), initialDict
    ))

    return dict({'vigor': yearDict.getInfo()})


def ee_query_class(roi: ee.Geometry.Polygon):
    
    class_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_integration_v2')
    selectedBand = class_asset.bandNames().size().subtract(1)
    
    last = class_asset.select(selectedBand)

    areaImg = ee.Image.pixelArea().divide(10000).addBands(last)

    stats = areaImg.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName='class'),
        geometry=roi,
        scale=30,
        maxPixels=1e13
    )
    groups = ee.List(stats.get('groups'));

    initialDict = ee.Dictionary();

    yearDict = ee.Dictionary(groups.iterate(
        lambda group, d: ee.Dictionary(d).set(
            ee.Dictionary(CLASSES.get('class')).get(ee.String(ee.Number(ee.Dictionary(group).get('class')).toInt())),
            ee.Number(ee.Dictionary(group).get('sum')).format('%.2f')
        ), initialDict
    ))

    return dict({'class': yearDict.getInfo()})


# TODO: Otimizar e tornar mais legivel. (Talvez criar uma função para cada operação)
def ee_query_pasture(coordinates: list) -> str:
    """
    Extração de estatísticas de pastagem (biomassa, vigor, idade e chuva).
    """
    try:
        roi = ee.Geometry.Polygon(coordinates)

        result = [ee_query_biomass(roi), ee_query_age(roi), ee_query_vigor(roi), ee_query_class(roi)]

        return result
    except Exception as e:
        raise MessageException(
            title="Ocorreu um erro ao consultar a API do GEE.",
            instructions=textwrap.dedent("""
                1. Peça desculpas ao usuário.
                2. Peça que o usuário tente novamente mais tarde.
                """)
            )
