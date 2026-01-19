import os
import datetime
import ee
import requests
import PIL

from io import BytesIO

from agno.tools import Toolkit, tool
from agno.tools.function import ToolResult
from agno.media import Image
from agno.run import RunContext

from app.hooks.validation_hooks import validate_car_hook

from app.utils.dummy_logger import log

GEE_SERVICE_ACCOUNT = os.environ.get('GEE_SERVICE_ACCOUNT')
GEE_KEY_FILE = os.environ.get('GEE_KEY_FILE')
GEE_PROJECT = os.environ.get('GEE_PROJECT')

if not GEE_SERVICE_ACCOUNT or not GEE_KEY_FILE:
    raise ValueError("GEE_SERVICE_ACCOUNT and GEE_KEY_FILE environment variables must be set.")

try:
    credentials = ee.ServiceAccountCredentials(GEE_SERVICE_ACCOUNT, GEE_KEY_FILE)
    
    ee.Initialize(credentials, project=GEE_PROJECT)
except Exception as e:
    print(f"Authentication failed: {e}")


# TODO: Escrever ferramenta para visualização da área de pastagem do usuário.

# TODO: Deveria ter um buffer para as laterais da imagem não encostarem na região do poligono.
# TODO: A imagem do satelite deveria estar inteira, e não cliped na região de interesse.
@tool(tool_hooks=[validate_car_hook], requires_confirmation=False)
def generate_property_image(run_context: RunContext) -> ToolResult:
    """
    Gera uma imagem de satélite da propriedade rural baseada nos dados do CAR do usuário
    armazenados na sessão. Esta função não requer parâmetros, pois recupera 
    automaticamente a geometria da fazenda do estado atual da conversa.

    Esta função deve ser chamada quando:
    - O usuário pedir para "ver", "mostrar" ou "gerar mapa" da fazenda/propriedade.
    - O usuário quiser visualizar o contorno da área (CAR) sobreposto ao terreno.

    Return:
        Retorna um objeto ToolResult contendo a imagem da propriedade do usuário em formato PNG e uma breve descrição.
    """
    roi = ee.Feature(run_context.session_state['car']['features'][0]).geometry()

    # TODO: É mais adequado pegar uma imagem do ano ou dos ultimos 6 meses?
    year = (datetime.date.today().year) - 1

    # TODO: O mês deveria ser dinâmico.
    sDate = ee.Date.fromYMD(year, 10, 1)
    eDate= sDate.advance(2, 'month')

    sentinel = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterBounds(roi)
        .filterDate(sDate, eDate)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE',10))
        .median()
    )

    vis_params = {"bands": ["B4","B3","B2"],"min": 0,"max": 3000}
    sentinel = sentinel.visualize(**vis_params)

    empty = ee.Image().byte()
    outline = empty.paint(ee.FeatureCollection(roi), 1, 3)
    outline = outline.updateMask(outline)
    outline_rgb = outline.visualize(**{"palette":['FF0000']})

    final_image = sentinel.blend(outline_rgb).clip(ee.Feature(roi))

    url = final_image.getThumbURL({"dimensions": 1024,"format": "png"})

    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
                
        img_pil = PIL.Image.open(BytesIO(response.content))
        buffer = BytesIO()
        img_pil.save(buffer, format="PNG")
                
        return ToolResult(
            content=f"Aqui está a imagem de satélite da área. O contorno vermelho indica a zona de amortecimento de 5km.",
            images=[Image(content=buffer.getvalue())]
        )

    except Exception as e:
        return ToolResult(content=f"Erro ao gerar imagem: {str(e)}")


@tool(tool_hooks=[validate_car_hook])
def query_pasture(run_context: RunContext) -> dict:
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

    car = run_context.session_state['car']

    if len(car['features']) == 0:
        return """
            Infelizmente não foi possível localizar sua propriedade rural (CAR) via SICAR.
            Nessas condições não é possível recuperar informações geográficas para sua propriedade
        """

    roi = ee.Feature(car['features'][0]).geometry()

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
        'car': run_context.session_state['car']
    }