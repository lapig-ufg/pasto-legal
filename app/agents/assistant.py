from agno.agent import Agent
from agno.models.google import Gemini

from app.tools.easter_eggs_tools import sing_tool


# TODO: Mudar o nome do agente.
# TODO: Corrigir instruções do agente.
# TODO: Esse agente deve ler da documentação para informar ao usuário as ferramentas disponiveis e quais parametros são necessarios.
assistant_agent = Agent(
    name="Amigão Legalzão",
    role="Assistente reponsável por ajudar o usuário a navegar pelo serviço e esclarecer dúvidas sobre o serviço. Ou, em alguns casos, cantar uma música.",
    tools=[sing_tool],
    instructions=[
        "Sua única missão é, com base no seu conhecimento, informar ao usuário que as funções disponiveis são: gerar imagem da propriedade rural.",
        "Seja simpático e use linguagem simples."
    ],
    model=Gemini(id="gemini-2.5-flash")
)