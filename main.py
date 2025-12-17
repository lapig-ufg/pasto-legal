from agno.agent import Agent
#from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os import AgentOS
from utils.whatsapp import Whatsapp

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

class SICARTool(Toolkit):

    def __init__(self, **kwargs):
        tools = [
            self.sicar
        ]

        instructions = dedent("""\
            This tool is specialized in retrieve data from rural properties (CAR, SICAR) in Brazil
            via the service SICAR.
        """)
        
        super().__init__(name="sicar_tool", tools=tools, instructions=instructions, **kwargs)
 
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
         You are an specialized agent in the livestock, grassland, pasture and rural properties (CAR, SICAR) in Brazil. 
         Be simple, direct and objective. Only answer questions related to the subjects that you are specialized.    
    """),
    tools=[
        SICARTool()
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
    debug_mode=False,
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
    
