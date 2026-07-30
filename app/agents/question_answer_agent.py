from pathlib import Path

from agno.agent import Agent
from agno.run import RunContext
from agno.utils.log import log_error

from app.configs.config import config
from app.tools.tts_tools import generate_speech


files = [
    '01-introducao-e-conceitos-basicos.md', 
    '04-analises-agronomicas-e-calculos.md',
    '07-realização-apoio-e-parceiros-institucionais.md',
    '08-metodologias-calculos-tecnicos.md'
    ]

knowledge_text = ""
knowledge_path = Path.cwd() / "docs/knowledge"
for file_name in files:
    try:
        file_path = knowledge_path / file_name
        with open(file_path, 'r', encoding='utf-8') as file:
            knowledge_text += file.read() + "\n\n"
    except FileNotFoundError:
        log_error(f"Erro: O arquivo {file_name} não foi encontrado.")


def get_instructions(run_context: RunContext):
    instructions = f"""
        <knowledge>
        {knowledge_text}
        <knowledge>

        <instructions>
        - Você é o guia oficial do sistema. Seu objetivo é ajudar o usuário a entender como a plataforma funciona.
        - Responda baseando-se EXCLUSIVAMENTE na sua base de conhecimento (manuais e documentações fornecidos).
        - Seja simples e didático, explicando os passos de forma simples para o pequeno produtor rural.
        - Seja o mais breve possível.
        - Use markdown no formato do WhatsApp. Não use bullet points.
        - Se o usuário solicitar áudio, responda normalmente em texto — o sistema fará a conversão.
        <instructions>
    """
    
    return instructions

question_answer_agent = Agent(
    name="Agente Q&A",
    role="Guia Oficial de Suporte, Manual Interativo e FAQ da Plataforma.",
    description=(
        "Este agente é o manual de instruções vivo e a central de suporte da plataforma ao usuário. "
        "Deve ser acionado quando a intenção do usuário for puramente informativa ou educativa:\n"
        "- Perguntas sobre 'como fazer', 'onde clicar', 'como iniciar' ou como navegar pelas funcionalidades.\n"
        "- Explicações sobre terminologias, o significado de métricas (ex: 'o que é NDVI?') ou dúvidas conceituais.\n"
        "- Quando o usuário pergunta quais dados o sistema possui, quais mapas ele pode gerar ou quais são os limites do sistema.\n"
        "- Qualquer dúvida geral resolvida estritamente através da leitura de manuais e documentações internas.\n\n"
        "Direcione para cá mensagens com gatilhos de suporte (ex: 'me ajuda', 'como eu faço', 'não entendi', 'o que significa isso?').\n"
    ),
    debug_mode=config.DEBUG_MODE,
    use_instruction_tags=False,
    instructions=get_instructions,
    model=config.model,
    tools=[
        generate_speech
    ]
)