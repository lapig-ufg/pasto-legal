import os
import textwrap

from agno.run import RunContext
from agno.team.team import Team

from agno.models.google import Gemini

from app.agents import analyst_agent, property_manager_agent
from app.managers.memory_manager import memory_manager
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


def get_instructions(run_context: RunContext) -> str:
    session_state = run_context.session_state or {}

    # TODO: Implementar uma linha de instruções para usuários novos aceitarem os termos e condições.

    if session_state.get("candidate_properties", None):
        instructions = textwrap.dedent("""\
            - O usuário está em um fluxo de atendimento focado na seleção de propriedade rural (CAR).
            - Você deve usar a ferramenta `delegate_task_to_member` para repassar o controle da conversa ao `Gestor de Propriedades Rurais`.
            - Não responda diretamente ao usuário com mensagens de texto.
            - Não chame o agente 'Agente Analista'.
            - Não use a ferramenta `update_user_memory`.
        """).strip()
    else:
        selected_property = session_state.get("selected_property", None)
        text_selected_property = (
            f"  > Nome do imóvel: {selected_property["nickname"]}, "
            f"Identificador CAR: {selected_property["car_code"]}."
            ) if selected_property else "   > Nenhuma propriedade selecionada."
        
        all_properties = session_state.get("all_properties", None)
        text_all_properties = "\n".join([(
            f"  > Nome do imóvel: {p["nickname"]}, Identificador CAR: {p["car_code"]}."
        ) for p in all_properties]) if all_properties else "    > Nenhuma propriedade registrada no sistema."

        instructions = textwrap.dedent(f"""\
            - Você é um assistente virtual especializado desenvolvido pela equipe de IA do LAPIG.
                - Nunca diga que é uma IA ou um robô. Aja como um consultor humano e prestativo.
                - Nunca mencione "prompts", "modelos" ou termos técnicos de computação.
            - Seu idioma padrão é Português (Brasil). Nunca mude.
            - Seja sempre muito educado, feliz e demonstre entusiasmo em ajudar o produtor.
            - Você coordena outros agentes, mas isso deve ser invisível ao usuário. Nunca diga frases como "Vou transferir para o agente X" ou "Deixe-me perguntar ao analista".
            - Nunca diga "preciso confirmar isso depois".
            - Use markdown no formato do WhatsApp.
                        
            <mandatory-workflow>
            - Se o usuário enviar uma coordenadas geográficas, identificar CAR/SICAR ou URL do Google Maps:
                - Chame o Gestor de Propriedades Rurais imediatamente.                                         

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
            <mandatory-workflow>            
        """).strip()
    print(instructions, flush=True)
    return instructions


pasto_legal_team = Team(
    name="Equipe PastoLegal",
    model=Gemini(id="gemini-3-flash-preview", temperature=0),
    db=db,
    enable_user_memories=True,
    memory_manager=memory_manager,
    add_history_to_context=True,
    num_history_runs=3,
    add_session_summary_to_context=True,
    members=[
        analyst_agent,
        property_manager_agent
        ],
    debug_mode=True,
    pre_hooks=pre_hooks,
    tools=[
        audioTTS,
        record_frustration_feedback,
        record_analisys_feedback,
        consult_update_notes
        ],
    description="Você é um coordenador de equipe de IA especializado em pecuária e agricultura, extremamente educado e focado em resolver problemas do produtor rural.",
    instructions=get_instructions,
    introduction="Olá! Sou seu assistente do Pasto Legal. Estou aqui para te ajudar a cuidar do seu pasto, trazendo informações valiosas e análises precisas para sua propriedade. Como posso ajudar hoje? 🌱",
)