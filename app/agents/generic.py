import textwrap

from agno.agent import Agent
from agno.models.google import Gemini


# TODO: Implementar o agente analista.
generic_agent = Agent(
    name="Interpretador de imagens",
    role="Responsável por responder a dúvidas do usuário em relação a imagens fornecidas por ele. Capaz de interpretar imagens fornecidas pelo usuário.",
    description="Responsável por responder a dúvidas do usuário em relação a imagens fornecidas por ele. Capaz de interpretar imagens fornecidas pelo usuário.",
    instructions= textwrap.dedent("""                                  
       Responda as dúvidas do usuário em relação a imagem fornecida por ele.
    """),
    model=Gemini(id="gemini-2.5-flash")
)