from agno.agent import Agent
#from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp

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

class SICARTool(Toolkit):

    def __init__(self, **kwargs):
        tools = [
            self.sicar
        ]

        instructions = "Recuperação do limite do cadastro ambiental rural (CAR) via serviço SICAR"
        
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

load_dotenv()
console = Console()

app_db = SqliteDb(db_file="tmp/memory.db", memory_table="memory")
mem_db = SqliteDb(db_file="tmp/memory.db", memory_table="agent_storage")

memory = Agent(
    model=Gemini(id="gemini-2.5-flash"),
    db=mem_db,
    instructions=dedent("""\
        You are a helpful assistant that manages user memories.
        Your goal is to store relevant information about the user to improve future interactions.
        Always remember to keep the memories concise and relevant.
        
        Collect User's name,
        Collect User phone number,
        Collect Information about bad behaviours as a rudeness counter,
        Collect Information about user gender,
        Collect Information about user location,
        Collect Information about user age,
        Collect Information about user's passion and hobbies,
        Collect Information about the users likes and dislikes
    """),
    # Give the Agent the ability to update memories
    enable_agentic_memory=True,
    # OR - Run the MemoryManager automatically after each response
    enable_user_memories=True,
    markdown=True,
)

pasto_legal = Agent(
    name="Pasture Searcher",
    role="You can only answer questions related to the Pasture program in Brazil.",
    model=Gemini(id="gemini-2.5-flash", search=True),
    db=mem_db,
    session_state={"car": None},
    tools=[
        SICARTool()
    ],
    num_history_runs=5,
    markdown=False,
    instructions=dedent("""\
         You are an specialized agent in the Pasture program in Brazil. Be simple, direct and objective.
         Only answer questions related to the Pasture program in Brazil.    
    """)
)

multi_language_team = Team(
    db=app_db,
    name="PastoLegal Team",
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
        pasto_legal
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
       ** If you receive a location, tell to the user where is the nearest CRAS and save this location into the memory.**
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

agent_os = AgentOS(
    teams=[multi_language_team],
    interfaces=[
        Whatsapp(team=multi_language_team)
    ],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="example_main:app", port=3000, reload=True) 
    
