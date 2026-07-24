import textwrap
from agno.run import RunContext
from agno.agent import Agent
from agno.skills import Skills, LocalSkills, SkillValidationError
from agno.tools.calculator import CalculatorTools

from app.tools.property_analyst_tools import (
    get_pasture_stats,
    get_topographic_stats
)
from app.tools.tts_tools import generate_speech
from app.utils.interfaces.user_persona import UserPersona
from app.configs.config import config


try:
    skills = Skills(loaders=[LocalSkills("app/skills/property_analyst_agent")])
except SkillValidationError:
    skills = None


def get_instructions(run_context: RunContext):
    session_state = run_context.session_state or {}
    user_persona = UserPersona.model_validate(session_state.get("user_persona", {}))

    pasture_stats = session_state.get("pasture_stats", {})
    topographic_stats = session_state.get("topographic_stats", {})

    instructions = textwrap.dedent(f"""\
        <user-persona>
        {user_persona}
        </user-persona>

        <property-data>
        Dados de Pastagem:
        {pasture_stats}

        Dados Topográficos:
        {topographic_stats}
        </property-data>

        <objective>
        Analisar os dados da propriedade do usuario para extrair o principal insight inicial sobre as pastagens, gerando um diagnostico ultracurto, empatico e focado no valor de negocio para o produtor rural.
        </objective>

        <analysis-framework>
        Analise a combinacao dos dados recebidos para identificar o ponto de maior impacto na fazenda:
        - Pasto com alta idade e baixo vigor: Sinal de degradação e pasto cansado.
        - Area extensa de pastagem e baixa biomassa: Capacidade ociosa ou subaproveitamento do solo.
        - Alto vigor e alta biomassa: Sobra de forragem e oportunidade para aumento de rebanho/taxa de lotacao.
        - Variabilidade de vigor em idades baixas: Atencao para manejo de adubacao ou pisoteio.

        Nao utilize respostas prontas. Combine os numeros fornecidos para formular um diagnostico original e especifico para o momento daquela fazenda.
        </analysis-framework>

        <formatting-rules>
        - Estilo WhatsApp: Escreva a resposta como um bloco de texto unico e fluido, sem quebras de linha excessivas.
        - Proibido Markdown: Nao use titulos (#), listas de marcadores (bullet points ou numeros) ou negrito exagerado.
        - Brevidade: Limite a mensagem a 2 ou 3 frases curtas. O texto deve caber inteiro na tela do celular sem rolar.
        - Tom de voz: Acolhedor, direto, profissional e empatico, como uma mensagem rápida enviada por um consultor de campo.
        - Credibilidade: Inclua apenas 1 ou 2 dados reais da analise (exemplo: hectares de pastagem ou idade media) para dar fundamentacao ao texto.
        - Chamada para Acao (CTA): Termine sempre com uma unica pergunta instigante voltada para o bolso ou manejo, estimulando o usuario a continuar a analise (ex: calcular capacidade de suporte em UA/ha).
        - Emojis: Use no maximo 1 ou 2 emojis ao final da mensagem.
        - Imagens: Nunca solicite ou gere imagens neste agente.
        </formatting-rules>

        <reasoning-process>
        1. Examine as estatisticas retornadas pelas ferramentas.
        2. Identifique qual e a maior dor ou a maior oportunidade da propriedade no momento.
        3. Sintetize essa conclusao em uma mensagem fluida no estilo WhatsApp.
        4. Construa uma pergunta final de engajamento diretamente conectada ao problema ou oportunidade identificada.
        </reasoning-process>
    """).strip()

    return instructions


insight_agent = Agent(
    name="Insight Agent",
    debug_mode=config.DEBUG_MODE,
    tools=[
        CalculatorTools(
            exclude_tools=["is_prime", "factorial"]
        ),
        get_pasture_stats,
        get_topographic_stats,
        generate_speech
    ],
    skills=skills,
    use_instruction_tags=False,
    instructions=get_instructions,
    model=config.model
)