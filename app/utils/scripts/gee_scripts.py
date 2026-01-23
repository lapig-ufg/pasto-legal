import os
import ee
import PIL
import datetime
import requests
import textwrap
import geemap as gee

from PIL import Image

from io import BytesIO

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
        '49':'Restinga Arbórea',
        '11':'Campo Alagado e Área Pantanosa',
        '12':'Formação Campestre',
        '32':'Apicum',
        '29':'Afloramento Rochoso',
        '50':'Restinga Herbácea',
        '15':'Pastagem',
        '19':'Lavoura Temporária',
        '39':'Soja',
        '20':'Cana',
        '40':'Arroz',
        '62':'Algodão',
        '41':'Outras Lavouras Temporárias',
        '36':'Lavoura Perene',
        '46':'Café',
        '47':'Citrus',
        '35':'Dendê',
        '48':'Outras Lavouras Perenes',
        '9':'Silvicultura',
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
        '1-10': 0, 
        '10-20': 0, 
        '20-30': 0, 
        '30-40': 0, 
        'area_total_ha': 0
    }
}

# TODO: Otimizar e tornar mais legivel.
def retrieve_feature_images(geo_json: dict) -> PIL.Image:
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

    sentinel = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
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
            img_pil = Image.open(BytesIO(resposta.content))

            result.append(img_pil)

        return result
    # TODO: Mapear possíveis erros.
    except Exception as e:
        # TODO: Melhorar a menssagem de erro. Com motivo do erro e instrução de execução.
        raise Exception(f"Erro ao gerar imagem: {str(e)}")

   
def aggregateDate(img:dict,roi:dict,scale:int) -> dict:
    """
    Calculo da estatística zonal.
    """
    stats = img.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1,groupName='class'),
        geometry=roi,
        scale=scale,
        maxPixels=1e13
    )

    return stats


def group_values_age_ee(dados: dict):
    """
    Agrega valores de um dicionário ee.Dictionary em 4 classes de idade.
    Processamento realizado no servidor do Google Earth Engine.
    """
    # 1. Template de agregação (Acumulador inicial)
    inicial =  CLASSES['age']

    # Garante que a entrada seja um ee.Dictionary
    dict_dados = ee.Dictionary(dados)

    # 2. Função de iteração
    def iterate_logic(key, acc):
        acc = ee.Dictionary(acc)
        key_str = ee.String(key)
        valor = ee.Number(dict_dados.get(key_str)).round()
        
        # Arredondar para duas casas decimais no servidor
        valor = valor.multiply(100).round().divide(100)
        
        # Tenta converter chave para número (default 999 para chaves de texto)
        id_num = ee.Number.parse(key_str)

        # Lógica de agrupamento com ee.Algorithms.If aninhado
        # Nota: Usamos .And() (com A maiúsculo) para objetos ee.Number
        grupo = ee.Algorithms.If(id_num.lte(10), '1-10',
                ee.Algorithms.If(id_num.gt(10).And(id_num.lte(20)), '10-20',
                ee.Algorithms.If(id_num.gt(20).And(id_num.lte(30)), '20-30', 
                ee.Algorithms.If(id_num.gt(30).And(id_num.lte(40)), '30-40', 
                key_str)))) # Mantém a chave original se for texto (ex: area_total_ha)

        # Soma o valor ao que já existia no grupo dentro do acumulador
        valor_antigo = ee.Number(acc.get(grupo, 0))
        
        return acc.set(grupo, valor_antigo.add(valor))
    
    resultado = dict_dados.keys().iterate(iterate_logic, inicial)

    return ee.Dictionary(resultado)


# TODO: Tipar o 'roi'.
def ee_query_biomass(roi):
    biomass_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_biomass_v2')
    selectedBand = biomass_asset.bandNames().size().subtract(1)
    last = biomass_asset.select(selectedBand)

    last = last.multiply(ee.Image.pixelArea().divide(10000))

    stats = last.reduceRegion(
                  reducer=ee.Reducer.sum(),
                  geometry=roi,
                  scale=30,
                  maxPixels=1e13)

    return dict({'biomass': stats.getInfo()})


# TODO: Tipar o 'roi'.
def ee_query_age(roi):
    age_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_age_v2')
    selectedBand = age_asset.bandNames().size().subtract(1)
    last = age_asset.select(selectedBand)

    last = last.subtract(200)
    last = last.where(last.eq(-100), 40).rename('Anos');

    stats = last.reduceRegion(reducer=ee.Reducer.frequencyHistogram(), geometry=roi, scale=30, maxPixels=1e13)
    
    return dict({'age': group_values_age_ee(stats.get('Anos')).getInfo()})


# TODO: Tipar o 'roi'.
def ee_query_vigor(roi):
    vigor_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_vigor_v3')
    selectedBand = vigor_asset.bandNames().size().subtract(1)
    last = vigor_asset.select(selectedBand)

    areaImg = ee.Image.pixelArea().divide(10000).addBands(last)

    stats = aggregateDate(areaImg, roi,30)
    groups = ee.List(stats.get('groups'));

    totalArea = ee.Number(groups.iterate(
        lambda item, sum_val: ee.Number(sum_val).add(ee.Dictionary(item).get('sum')),0
    ))

    initialDict = ee.Dictionary({
        'area_total_ha': ee.Number(totalArea).format('%.2f')
    });

    yearDict = ee.Dictionary(groups.iterate(
        lambda group, d: ee.Dictionary(d).set(
            ee.Dictionary(CLASSES.get('vigor')).get(ee.String(ee.Number(ee.Dictionary(group).get('class')).toInt())),
            ee.Number(ee.Dictionary(group).get('sum')).format('%.2f')
        ), initialDict
    ))

    return dict({'vigor': yearDict.getInfo()})


# TODO: Tipar o 'roi'.
def ee_query_class(roi):
    class_asset = ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_integration_v2')
    selectedBand = class_asset.bandNames().size().subtract(1)
    last = class_asset.select(selectedBand)

    areaImg = ee.Image.pixelArea().divide(10000).addBands(last)

    stats = aggregateDate(areaImg,roi,30)
    groups = ee.List(stats.get('groups'));

    totalArea = ee.Number(groups.iterate(
        lambda item, sum_val: ee.Number(sum_val).add(ee.Dictionary(item).get('sum')),0
    ))

    initialDict = ee.Dictionary({
        'area_total_ha': ee.Number(totalArea).format('%.2f')
    });

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