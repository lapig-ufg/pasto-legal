from typing import Optional, Sequence

from agno.agent import Agent
from agno.media import Image
from agno.models.google import Gemini
from agno.run.agent import RunInput

from app.utils.dummy_logger import log

def analyze_image(user_text: str, images: Optional[Sequence[Image]]) -> str:
    """
    Analisa imagem do usuário.

    Args:
        user_text: A dúvida do usuário.
        images: Imagens injetadas automaticamente pelo framework.

    Return:
        ToolResult: Objeto contendo a análise da imagem.
    """
    log(images)

    inner_agent = Agent(
        model=Gemini(id="gemini-2.5-flash"),
        instructions=[
            "Você é um assistente que analisa imagens. "
            "Responda a dúvida do usuário em relação a imagem. "
        ],
    )
    
    response = inner_agent.run(RunInput(input_content=user_text, images=images))
    
    return response.content