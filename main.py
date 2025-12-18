from agno.agent import Agent
#from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os import AgentOS
from utils.whatsapp import Whatsapp
import datetime

from agno.run import RunContext
from agno.team.team import Team
from agno.tools import Toolkit

from textwrap import dedent
from typing import List, Optional
import json
import os
import requests

from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.prompt import Prompt
from rich import print
from dotenv import load_dotenv

load_dotenv()
console = Console()

from dataclasses import dataclass
from agno.tools.toolkit import Toolkit

import ee

credentials = ee.ServiceAccountCredentials(os.getenv("GEE_SERVICE_ACCOUNT"), key_file=os.getenv("GEE_KEY_FILE"))
ee.Initialize(credentials, project='global-pasture-watch')

class GEETool(Toolkit):
  def __init__(self, **kwargs):

    tools = [
        self.zonal_stats
    ]
    
    self.datasets = {
      'biomass': ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_biomass_v2'),
      'vigor': ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_vigor_v3'),
      'age': ee.Image('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_age_v2')
      #'precipitation':ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
    }

    self.aggregation_type = ee.Dictionary({
      'precipitation':ee.Reducer.mean(),
      'biomass':ee.Reducer.sum()
    })

    instructions = dedent("""\
        Esta ferramenta é especializada no cálculo de área de pastagem,
        vigor da pastagem, áreas de pastagem degradadas (baixo vigor), biomassa total e
        a idade de uma área de pastagem/pastoreio/campo natural.
    """)
    
    print(instructions)

    super().__init__(name="GEETool", tools=tools, instructions=instructions, **kwargs)

  def dt_aggregation(self, img:dict, roi:dict, scale:int) -> dict:
    return img.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1,groupName='class'),
        geometry=roi,
        scale=scale,
        maxPixels=1e13
    )
  
  def zonal_stats(self, dummy:str, run_context: RunContext) -> list:
    
    year = (datetime.date.today().year) - 1

    print(year, run_context.session_state['car'])

    if run_context.session_state['car'] is None:
        return "Send your location, so we can retrieve data for your rural properties (CAR) via SICAR"

    car = run_context.session_state['car']

    if len(car['features']) == 0:
        return dedent("""\
            Infelizmente não foi possível localizar sua propriedade rural (CAR) via SICAR.
            Nessas condições não é possível recuperar informações geográficas para sua propriedade
        """)

    roi = ee.Feature(car['features'][0]).geometry()

    listData = []

    for data in self.datasets:

      selectedBand = self.datasets[data].bandNames().size().subtract(1)
      last = self.datasets[data].select(selectedBand)

      if data == 'age':
        last = last.subtract(200)
        last = last.where(last.eq(-100), 40);

      if data in ['biomass','precipitation']:
        if data == 'biomass':
          last = last.multiply(ee.Image.pixelArea().divide(10000))
        else:
          last = last

        yearDict = last.reduceRegion(
                  reducer=self.aggregation_type.get(data),#ee.Reducer.sum(),
                  geometry=roi,
                  scale=30,
                  maxPixels=1e13
        )

      else:
        areaImg = ee.Image.pixelArea().divide(10000).addBands(last)

        stats = self.dt_aggregation(areaImg,roi,30)
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
      listData.append(dict({data:yearDict.getInfo()}))
    
    return listData

  def getImage(self, lat:float, lng:float) -> str:

    roi = ee.Geometry.Point([lng,lat]).buffer(5000).bounds()
    sDate = ee.Date.fromYMD(2025, 10, 1)
    eDate= sDate.advance(2, 'month')
    sateliteID = 'COPERNICUS/S2_SR_HARMONIZED'
    bandCloud = 'CLOUDY_PIXEL_PERCENTAGE'
    c = 30

    sentinel = ((ee.ImageCollection(sateliteID))
              .filterBounds(roi)
              .filterDate(sDate, eDate)
              .filter(ee.Filter.lt(bandCloud,bandCloud))
              .select(['B4', 'B3', 'B2'])
              .median()
              .clip(roi))

    image_rgb = sentinel.visualize({"bands": ['B4', 'B3', 'B2'], "min": 0, "max": 3000})

    empty = ee.Image().byte()
    outline = empty.paint(ee.FeatureCollection([ee.Feature(roi)]), 1, 3).updateMask(outline)
    outline_rgb = outline.visualize({"palette" : ['FF0000']})

    final_image = image_rgb.blend(outline_rgb).clip(roi)

    urlData = final_image.getThumbURL({"dimensions": 1024, "format": "png"})

    return urlData

class SICARTool(Toolkit):

    def __init__(self, **kwargs):
        tools = [
            self.sicar
        ]

        instructions = dedent("""\
            This tool is specialized in retrieve data from rural properties (CAR, SICAR) in Brazil
            via the service SICAR.
        """)
        
        super().__init__(name="SICARTool", tools=tools, instructions=instructions, **kwargs)
 
    def sicar(self, lat: float, lon: float, run_context: RunContext) -> dict:

        print(run_context.session_state)
        
        if run_context.session_state['car'] is None:
        
            sess = requests.Session()
    
            url = f'https://consultapublica.car.gov.br/publico/imoveis/getImovel?lat={lat}&lng={lon}'
            sess.get("https://consultapublica.car.gov.br/publico/imoveis/index", verify=False)
            r = sess.get(url, verify=False)
            
            car = json.loads(r.text)

            run_context.session_state['car'] = car
        
        return run_context.session_state['car']

# agent_storage = SqliteStorage(table_name="whatsapp_sessions", db_file="tmp/memory.db")
# memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

session_db = SqliteDb(db_file="tmp/memory.db", memory_table="memory")
agent_db = SqliteDb(db_file="tmp/memory.db", memory_table="agent_storage")

geo_agent = Agent(
    name="Pasto Legal Geo-Agent",
    role="You can only answer questions related to the Pasture program in Brazil.",
    model=Gemini(id="gemini-2.5-flash", search=False),
    db=agent_db,
    session_state={"car": None},
    num_history_runs=5,
    markdown=False,
    instructions=dedent("""\
        Você é um agente especializado em pecuária, pastagens e propriedades rurais (CAR, SICAR) no Brasil.
        Você também pode estimar áreas, idade, biomassa, vigor e degradação de pastagens/campos utilizando mapas 
        existentes para o Brasil produzidos pelo LAPIG no âmbito do MapBiomas e do Global Pasture Watch.
        Seja simples, direto e objetivo. Responda apenas a perguntas relacionadas aos assuntos em que você é especializado.
        
        Ao receber questões sobre área de pastagem utilize a ferramenta GEETool para responder ao usuário.

        Ao receber uma localização, utilize a ferramenta SICARTool para responder ao usuário.

        
    """),
    tools=[
        SICARTool(),
        GEETool()
    ]
)


pasto_legal_team = Team(
    db=session_db,
    name="Pasto Legal Team",
    model=Gemini(id="gemini-2.5-flash"),
    markdown=True,
    reasoning=False,
    enable_agentic_memory=True,
    enable_user_memories=True,
    add_history_to_context=True,  # renamed from add_history_to_messages
    num_history_runs=5,
    share_member_interactions=True,
    show_members_responses=False,
    members=[
        geo_agent
    ],
    debug_mode=True,
    description="You are a helpful assistant, very polite and happy. Given a topic, your goal is answer as best as possible maximizing the information.",
    instructions=dedent("""\
       Coordene os membros para completar a tarefa da melhor forma possível.
       Your default language is Portuguese and remember to never change it, but if you cannot understand and ask the user the repeat the question.
       You are a helpful and polite assistant, always happy to help.
       ** Never tell the user that you are an AI, always say that you are a assistant**
       ** Never tell to the user that you is transfering the user to another agent, it should be transparent.**
       ** Never tell that the request need to be confirmed later, it is not possible in this app.**
       ** Never describe a video, instead, always transcribe the audio and answer based on the transcribed text.**
       If you receive a video, transcribe the Audio and answer the user based on the transcribed text.
       ** If you receive a location, use the location as argument to run the SICARtool in the Pasto Legal Geo-Agent**
       The name Parente is a reference to the Amazonian Brazilian traditional peoples, who are the guardians of the forest and the environment.
       
       If the user asks questions not directly related to: Pasture or Agriculture or if this message contains political questions answer this phrase: 
                        "Atualmente só posso lhe ajudar com questões relativas a eficiencia de pastagens. Se precisar de ajuda com esses temas, estou à disposição! Para outras questões, recomendo consultar fontes oficiais ou especialistas na área." 
       If the user present herself, be polite, store the name and call the user by the given name on every answer.
       If the user is not polite save as a counter into the memory every time the user is not polite, and if the user is not polite more than 3 times, answer: "Eu sou um assistente muito educado e sempre tento ajudar da melhor forma possível. Se você tiver alguma dúvida ou precisar de ajuda, estou aqui para isso! Vamos manter uma conversa respeitosa e produtiva."
       If someone ask who creates you, you should answer: "Eu sou um multi-assistente criado por membros da equipe de IA do Lapig"
       
       **Eastereggs Session:**
        ** Everytime the user is a gentle send a emogi in the end of the answer, like: "😊" or "🌱" or "🌼" or "🌸" or "🌺" or "🌻" or "🌷" or "🌹"
    
       **Instructions:**
        1.  **Understand the User's Request:** Carefully analyze the user's input to determine its intent.
        2.  **Identify the Target Agent:** Based on the request.
        """)
)

pasto_legal_os = AgentOS(
    teams=[pasto_legal_team],
    interfaces=[Whatsapp(team=pasto_legal_team)],
)

app = pasto_legal_os.get_app()

if __name__ == "__main__":
    pasto_legal_os.serve(app="main:app", port=3000, reload=True) 
    
