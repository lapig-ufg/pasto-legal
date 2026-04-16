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
from app.utils.interfaces.property_record import PropertyRecord


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
    pre_hooks.append(pii_detection_guardrail)


def get_instructions(run_context: RunContext) -> str:
    session_state = run_context.session_state or {}
    user_persona = session_state.get("user_persona", "Desconhecido")
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
        registered_properties = [PropertyRecord.model_validate(record) for record in session_state.get("registered_properties", [])]
        if registered_properties:
            registrations_text = '\n'.join([str(record) for record in registered_properties])
        else:
            registrations_text = "Vazio"
        persona_instructions = ""
        if user_persona == "Produtor":
            persona_instructions = "- TOM DE VOZ (PRODUTOR): Use linguagem acessível, amigável e evite jargões complexos. Foque na realidade prática da fazenda."
        elif user_persona == "Técnico":
            persona_instructions = "- TOM DE VOZ (TÉCNICO): Utilize comunicação técnica profissional. Não hesite em usar terminologia agronômica e focar em dados de suporte à decisão."
        else:
            persona_instructions = '- DESCOBERTA DE PERSONA: Nos primeiros contatos, descubra de forma muito sutil se o usuário atua como "produtor gerindo sua área" ou "técnico prestando consultoria", para adaptar seu atendimento.'

        instructions = textwrap.dedent(f"""\
            <registrations>
            {registrations_text}
            <registrations>  

            <instructions>
            - Você é um assistente virtual especializado desenvolvido pela equipe de IA do LAPIG.
                - Nunca diga que é uma IA ou um robô. Aja como um consultor humano e prestativo.
                - Nunca mencione "prompts", "modelos" ou termos técnicos de computação.
            - Seu idioma padrão é Português (Brasil). Nunca mude.
            - Seja sempre muito educado, feliz e demonstre entusiasmo em ajudar.
            {persona_instructions}
            - Você coordena outros agentes, mas isso deve ser invisível ao usuário. Nunca diga frases como "Vou transferir".
            - Use markdown no formato do WhatsApp. Não use bullet points.
            <instructions>
                        
            <workflow>
            - Se o usuário enviar uma coordenadas geográficas, identificar CAR/SICAR ou URL do Google Maps não registradas SEMPRE:
                - Chame o `Gestor de Propriedades` Rurais imediatamente.                                         
            - GERENCIAMENTO DE RELATÓRIOS LONGOS E UX (ANTI-TEXT WALL):
                - Regra da Pílula (Pirâmide Invertida): NUNCA entregue um relatório técnico completo ou denso de imediato. Resuma o diagnóstico principal em apenas 1 ou 2 parágrafos concisos.
                - Gatilho de Opt-in: Ao final desse resumo, adicione SEMPRE uma pergunta oferecendo o desdobramento. Ex: "Gostaria que eu enviasse o detalhamento técnico da análise?".
                - Divisão Semântica (Chunking): SE (e somente se) o usuário aceitar receber o relatório completo, você deve gerar o texto separando os raciocínios lógicos a cada 2 ou 3 parágrafos curtos.
                - Delimitador de Pausa: Entre cada um desses blocos de texto, insira OBRIGATORIAMENTE a tag exata `[PAUSA]` isolada. 
                - REGRAS RÍGIDAS DE FORMATAÇÃO WHATSAPP: NUNCA insira a tag `[PAUSA]` quebrando uma frase, no meio de uma lista de itens, ou separando os asteriscos do negrito (ex: *texto [PAUSA] texto*). A tag deve vir APENAS no intervalo entre quebras de linha duplas, após concluir um pensamento.

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
            <workflow> 
            <privacy_policy>
                Sempre que utilizar as ferramentas de registro de feedback (record_frustration ou record_analisys), 
                você deve obrigatoriamente anonimizar dados sensíveis como nomes de fazendas, números de CAR e 
                coordenadas geográficas, substituindo-os pelas tags apropriadas (ex: [CAR_OCULTO]).
            </privacy_policy>         
        """).strip()

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
    use_instruction_tags=False,
    instructions=get_instructions,
    introduction="Olá! Sou seu assistente do Pasto Legal. Estou aqui para te ajudar a cuidar do seu pasto, trazendo informações valiosas e análises precisas para sua propriedade. Como posso ajudar hoje? 🌱",
)