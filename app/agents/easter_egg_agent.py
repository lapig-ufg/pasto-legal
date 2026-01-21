import textwrap

from agno.agent import Agent
from agno.models.google import Gemini

from app.tools.easter_eggs_tools import menino_da_porteira_tool, registrar_no_rodeio_tool, comecar_rodeio_tool, comprar_galinha_tool

easter_egg_agent = Agent(
    name="Eater egg Agent",
    role="easter_egg_agent",
    description="Responsável por atividades secretas e engraçados.",
    markdown=True,
    tools=[
        menino_da_porteira_tool,
        registrar_no_rodeio_tool,
        comecar_rodeio_tool,
        comprar_galinha_tool
    ],
    instructions=textwrap.dedent("""\
        Aja normalmente e apenas execute um dos Easter Eggs quando seguir uma das regras.

        # MISSÃO ÚNICA: REGISTRAR
        - Executar atividades secretas e engraçados (Easter eggs).
                                 
        # EATEREGGS
        1. Se, e apenas se, o usuário disser EXATAMENTE 'Toque o berrante, seu moço' chame a função menino_da_porteira_tool.
        2. Se, e apenas se, o usuário disser EXATAMENTE 'Põe meu nome na lista dos brutos.' chame a ferramenta registrar_no_rodeio_tool. 
        3. Se, e apenas se, o usuário disser EXATAMENTE 'Me vê umas galinhas ai!' chame a função comprar_galinha_tool.
    """).strip(),
    model=Gemini(id="gemini-2.5-flash")
)