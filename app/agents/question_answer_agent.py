from pathlib import Path

from agno.run import RunContext
from agno.agent import Agent

from app.configs.models import model


files = [
    '01-introducao-e-conceitos-basicos.md', 
    '04-analises-agronomicas-e-calculos.md',
    '07-realização-apoio-e-parceiros-institucionais.md',
    '08-metodologias-calculos-tecnicos.md'
    ]

knowledge_text = ""
knowledge_path = Path("/app/docs/knowledge")
for file_name in files:
    try:
        file_path = knowledge_path / file_name
        with open(file_path, 'r', encoding='utf-8') as file:
            knowledge_text += file.read() + "\n\n"
    except FileNotFoundError:
        print(f"Erro: O arquivo {file_name} não foi encontrado.")


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
        <instructions>
    """
    
    return instructions

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
    use_instruction_tags=False,
    instructions=get_instructions,
    model=model,
)