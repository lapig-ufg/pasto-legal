from agno.run import RunContext
from agno.agent import Agent
from agno.models.google import Gemini
from agno.knowledge.knowledge import Knowledge

from app.database.knowledge_db import vector_db

def get_instructions(run_context: RunContext):
    instructions = f"""
        <instructions>
        - Você é o guia oficial do sistema. Seu objetivo é ajudar o usuário a entender como a plataforma funciona.
        - Responda baseando-se EXCLUSIVAMENTE na sua base de conhecimento (manuais e documentações fornecidos).
        - Seja conciso e didático, explicando os passos de forma simples para o produtor rural.
        - Use markdown no formato do WhatsApp. Não use bullet points, use traços ou numeração simples.
        <instructions>
    """
    
    return instructions

knowledge_base = Knowledge(
    vector_db=vector_db
)

knowledge_base.insert(path="/app/docs/guides/04-analises-agronomicas-e-calculos.md")

question_answer_agent = Agent(
    name="Agente Guia do Sistema (Q&A)",
    role=(
        "Agente de suporte responsável por tirar dúvidas do usuário sobre o sistema. Ele não executa "
        "geoprocessamento diretamente, mas sabe exatamente como o sistema faz isso lendo a documentação. "
        "Deve ser acionado quando o usuário perguntar 'como fazer', 'o que significa', 'quais dados existem' "
        "ou precisar de ajuda com a navegação."
    ),
    description=(
        "Especialista no funcionamento da plataforma e atendimento ao usuário. Atua como um "
        "manual interativo e bibliotecário do sistema.\n"
        "Suas responsabilidades são:\n"
        "   - Responder perguntas frequentes (FAQ) sobre a plataforma.\n"
        "   - Ensinar o usuário a gerar mapas temáticos e interpretar análises do sistema.\n"
        "   - Consultar a base de conhecimento (documentos internos) para fornecer diretrizes exatas de uso.\n"
    ),
    debug_mode=True,
    knowledge=knowledge_base,
    search_knowledge=True,
    use_instruction_tags=False,
    instructions=get_instructions,
    model=Gemini(id="gemini-3-flash-preview")
)