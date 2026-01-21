import os
import ee
import datetime
import requests
import PIL

from io import BytesIO


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


def retrieve_feature_image(feature: dict) -> PIL.Image:
    """
    Gera uma imagem de satélite da propriedade rural baseada nos dados do CAR do usuário
    armazenados na sessão. Esta função não requer parâmetros, pois recupera 
    automaticamente a geometria da fazenda do estado atual da conversa.
    """
    roi = ee.Feature(feature).geometry()

    sDate = ee.Date.fromYMD(datetime.date.today().year - 1, datetime.date.today().month, 1)
    eDate= sDate.advance(1, 'year')

    sentinel = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(roi)
        .filterDate(sDate, eDate)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE',10))
        .median()
    )

    vis_params = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}
    sentinel = sentinel.visualize(**vis_params)

    empty = ee.Image().byte()
    outline = empty.paint(ee.FeatureCollection(roi), 1, 3)
    outline = outline.updateMask(outline)
    outline_rgb = outline.visualize(**{"palette": ['FF0000']})

    final_image = sentinel.blend(outline_rgb).clip(ee.Feature(roi))

    url = final_image.getThumbURL({"dimensions": 1024,"format": "png"})

    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
                
        return PIL.Image.open(BytesIO(response.content))
    # TODO: Mapear possíveis erros.
    except Exception as e:
        raise Exception(f"Erro ao gerar imagem: {str(e)}")

   
# TODO: Dividir a função em funções menores.
def ee_query_pasture(feature: dict) -> dict:
    """
    Calcula a área de pastagem, vigor da pastagem, áreas de pastagem degradadas (baixo vigor),
    biomassa total e a idade baseada nos dados do CAR do usuário armazenados na sessão. Esta função não
    requer parâmetros, pois recupera automaticamente a geometria da fazenda do estado atual da conversa..

    Return:
        Dicionário contendo a área de pastagem, vigor da pastagem, áreas de pastagem degradadas (baixo vigor), biomassa total e a idade.
    """
    DATASETS = {
        'age': ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_age_v2'),
        'vigor': ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_vigor_v3'),
        'biomass': ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_biomass_v2')
    }

    AGGREGATION_TYPE = ee.Dictionary({
        'biomass': ee.Reducer.sum(),
        'precipitation': ee.Reducer.mean()
    })

    roi = ee.Feature(feature).geometry()

    listData = []

    for data in DATASETS:
        selectedBand = DATASETS[data].bandNames().size().subtract(1)
        last = DATASETS[data].select(selectedBand)

        if data == 'age':
            last = last.subtract(200)
            last = last.where(last.eq(-100), 40);

        if data in ['biomass','precipitation']:
            if data == 'biomass':
                last = last.multiply(ee.Image.pixelArea().divide(10000))
            else:
                last = last

            yearDict = last.reduceRegion(
                    reducer=AGGREGATION_TYPE.get(data),#ee.Reducer.sum(),
                    geometry=roi,
                    scale=30,
                    maxPixels=1e13
            )

        else:
            areaImg = ee.Image.pixelArea().divide(10000).addBands(last)

            stats = areaImg.reduceRegion(
                reducer=ee.Reducer.sum().group(groupField=1, groupName='class'),
                geometry=roi,
                scale=30,
                maxPixels=1e13
            )
            
            groups = ee.List(stats.get('groups'));

            totalArea = ee.Number(groups.iterate(
                lambda item, sum_val: ee.Number(sum_val).add(ee.Dictionary(item).get('sum')),0
            ))

            initialDict = ee.Dictionary({
                'area_total_ha': ee.Number(totalArea).round()
            });

            yearDict = ee.Dictionary(groups.iterate(
                lambda group, d: ee.Dictionary(d).set(
                    ee.String(ee.Number(ee.Dictionary(group).get('class')).toInt()),
                    ee.Number(ee.Dictionary(group).get('sum')).divide(totalArea).multiply(100)
                ), initialDict
            ))

        listData.append(dict({data: yearDict.getInfo()}))

    return {
        'info': listData,
    }