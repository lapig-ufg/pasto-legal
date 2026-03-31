import os
import textwrap

from agno.run import RunContext
from agno.team.team import Team
from agno.memory import MemoryManager
from agno.session import SessionSummaryManager
from agno.models.google import Gemini

from app.agents import analyst_agent, sicar_agent
from app.database.agno_db import db
from app.tools.tts_tools import audioTTS
from app.tools.feedback_tools import record_frustration_feedback, record_analisys_feedback
from app.tools.version_tools import consult_update_notes
from app.hooks.pre_hooks import validate_phone_authorization
from app.guardrails.pii_detection_guardrail import pii_detection_guardrail


if not (APP_ENV := os.environ.get('APP_ENV')):
    raise ValueError("APP_ENV environment variables must be set.")

pre_hooks = []

if APP_ENV == "production":
    debug_mode = False
    pre_hooks.append(validate_phone_authorization)
    pre_hooks.append(pii_detection_guardrail)
elif APP_ENV == "stagging":
    debug_mode = True
    pre_hooks.append(validate_phone_authorization)
    pre_hooks.append(pii_detection_guardrail)
elif APP_ENV == "development":
    debug_mode = True
    pre_hooks = []


def get_instructions(run_context: RunContext) -> str:
    session_state = run_context.session_state or {}

    is_selecting_car = session_state.get("is_selecting_car", False)

    # TODO: Implementar uma linha de instruções para usuários novos aceitarem os termos e condições.

    if is_selecting_car:
        instructions = textwrap.dedent("""\
            - O usuário está em um fluxo de atendimento focado na seleção de propriedade rural (CAR).
            - Você deve usar a ferramenta `delegate_task_to_member` para repassar o controle da conversa ao 'Agente Sicar'.
            - NÃO responda diretamente ao usuário com mensagens de texto.
            - NUNCA chame o agente 'Agente Analista'.
            - NUNCA use a ferramenta `update_user_memory`.
        """).strip()
    else:
        instructions = textwrap.dedent("""\
            - Você é um assistente virtual especializado desenvolvido pela equipe de IA do LAPIG.
                - NUNCA diga que é uma IA ou um robô. Aja como um consultor humano e prestativo.
                - NUNCA mencione "prompts", "modelos" ou termos técnicos de computação.
            - Seu idioma padrão é Português (Brasil). NUNCA mude.
            - Seja sempre muito educado, feliz e demonstre entusiasmo em ajudar o produtor.
            - Você coordena outros agentes, mas isso deve ser INVISÍVEL ao usuário. NUNCA diga frases como "Vou transferir para o agente X" ou "Deixe-me perguntar ao analista".
            - NUNCA diga "preciso confirmar isso depois".
            - O sistema possui todas as informações necessárias para execução.
            - Use markdown no formato do WhatsApp.
                        
            <Fluxos de trbalho específicos>
            - Se o usuário enviar uma localização (coordenadas), código CAR (ex: UF-XXXXXXX-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX, ...) ou URL do Google Maps:
                - Chame IMEDIATAMENTE o agente `Agente Sicar`.
                - NÃO use a ferramenta `update_user_memory`.                                           

            - Se o usuário enviar um arquivo de áudio ou vídeo:
                - AÇÕES:
                    1. Ignore imagens visuais temporariamente e foque na transcrição do áudio.
                    2. Baseie sua resposta apenas no que foi falado.
                    3. Você DEVE OBRIGATORIAMENTE usar a ferramenta `audioTTS` (audio_generator) para gerar sua resposta em formato de áudio.
                - NUNCA:
                    1. NÃO descreva o ambiente visualmente (ex: "vejo um pasto verde") se o foco for a dúvida falada.
                    2. NÃO responda apenas em texto quando receber um áudio. A resposta final DEVE conter o áudio gerado pela sua ferramenta.

            - Se o usuário demonstrar frustração, disser que a resposta está errada ou que "não era isso que queria":
                - AÇÕES:
                    1. Pare de tentar explicar o assunto e peça desculpas IMEDIATAMENTE.
                    2. Diga que deseja aprender e pergunte: "Me desculpe por não entender. Como seria a resposta ideal que você esperava?"
                    3. Após o usuário fornecer a resposta desejada, você DEVE usar a ferramenta `registrar_feedback` passando a pergunta original (que gerou o erro), o motivo da frustração e a resposta que o usuário ensinou.
                    4. Agradeça a colaboração e retorne a conversa de forma amigável.
            <Fluxos de trbalho específicos>
        """).strip()

    return instructions

memory_manager = MemoryManager(
    model=Gemini(id="gemini-3-flash-preview", temperature=0),
    memory_capture_instructions=textwrap.dedent("""\
            Memories should capture personal information about the user that is relevant to the current conversation, such as:
            - Personal facts: name, age, occupation, interests, and preferences
            - Opinions and preferences: what the user likes, dislikes, enjoys, or finds frustrating
            - Significant life events or experiences shared by the user
            - Important context about the user's current situation, challenges, or goals
            - Any other details that offer meaningful insight into the user's personality, perspective, or needs
        """).strip(),
    additional_instructions="""Don't store any memories about coordinates, SICAR code or Google Map's URLs.""",
    db=db,
)

summary_manager = SessionSummaryManager(
    model=Gemini(id="gemini-3-flash-preview", temperature=0),
)

pasto_legal_team = Team(
    db=db,
    name="Equipe PastoLegal",
    model=Gemini(id="gemini-3-flash-preview", temperature=0),
    respond_directly=True,
    enable_user_memories=True,
    memory_manager=memory_manager,
    update_memory_on_run=True,
    determine_input_for_members=False,
    add_history_to_context=True,
    num_history_runs=3,
    add_team_history_to_members=True,
    num_team_history_runs=1,
    members=[
        analyst_agent,
        sicar_agent
        ],
    debug_mode=debug_mode,
    pre_hooks=pre_hooks,
    tools=[
        audioTTS,
        record_frustration_feedback,
        record_analisys_feedback,
        consult_update_notes
        ],
    description="Você é um coordenador de equipe de IA especializado em pecuária e agricultura, extremamente educado e focado em resolver problemas do produtor rural.",
    instructions=get_instructions,
    introduction="Olá! Sou seu assistente do Pasto Legal. Estou aqui para te ajudar a cuidar do seu pasto, trazendo informações valiosas e análises precisas para sua propriedade. Como posso ajudar hoje? 🌱"
)