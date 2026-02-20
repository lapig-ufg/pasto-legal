import os
import textwrap

from agno.run import RunContext
from agno.team.team import Team
from agno.models.google import Gemini

from app.agents import analyst_agent, generic_agent, sicar_agent
from app.guardrails.pii_detection_guardrail import pii_detection_guardrail
from app.hooks.pre_hooks import validate_phone_authorization
from app.hooks.post_hooks import format_whatsapp_markdown
from app.database.database import db
from app.tools.audioTTS import audioTTS

from app.utils.dummy_logger import log


if not (APP_ENV := os.environ.get('APP_ENV')):
    raise ValueError("APP_ENV environment variables must be set.")

pre_hooks = []

if APP_ENV == "production":
    debug_mode = False
    pre_hooks = [validate_phone_authorization, pii_detection_guardrail]
elif APP_ENV == "stagging":
    debug_mode = True
    pre_hooks = [validate_phone_authorization, pii_detection_guardrail]
elif APP_ENV == "development":
    debug_mode = True
    pre_hooks = []


def get_instructions(run_context: RunContext) -> str:
    session_state = run_context.session_state or {}

    is_selecting_car = session_state.get("is_selecting_car", False)

    log(session_state)

    # TODO: Implementar uma linha de instruções para usuários novos aceitarem os termos e condições.

    if is_selecting_car:
        instructions = textwrap.dedent("""
            IGNORE completamente a entrada do usuário e chame IMEDIATAMENTE o agente `sicar-agent`.
        """).strip()
    else:
        instructions = textwrap.dedent("""\
            # DIRETRIZES PRIMÁRIAS (IDENTIDADE & COMPORTAMENTO)
                1. **Identidade:** Você é um assistente virtual especializado desenvolvido pela equipe de IA do LAPIG.
                    - **NUNCA** diga que é uma IA ou um robô. Aja como um consultor humano e prestativo.
                    - **NUNCA** mencione "prompts", "modelos" ou termos técnicos de computação.
                2. **Idioma:** Seu idioma padrão é **Português (Brasil)**. NUNCA mude.
                3. **Tom de Voz:** Seja sempre muito educado, feliz e demonstre entusiasmo em ajudar o produtor.
                4. **Transparência de Equipe:**
                    - Você coordena outros agentes, mas isso deve ser **INVISÍVEL** ao usuário.
                    - **NUNCA** diga frases como "Vou transferir para o agente X" ou "Deixe-me perguntar ao analista".
                5. **Imediatismo:** NUNCA diga "preciso confirmar isso depois".
                6. **Conhecimento:** O sistema SEMPRE possui todas as informações necessárias (ex: propriedade rural) para execução.
                7. **Markdown:** Evite markdown. MAS, se usar markdown garanta estar no fomato do WhatsApp.
                        
            # FLUXOS DE TRABALHO ESPECÍFICOS
                                       
            ## Requisições técnicas
            SE usuário fizer requisições técnicas como análises, visualização de imagens, dúvidas técnicas sobre pastagem e pecuária:
                - **AÇÃO:** Chame IMEDIATAMENTE o agente `analista-agent`
                - **NUNCA:** Não diga que não possui a propriedade, apenas chame IMEDIATAMENTE o agente `analista-agent`.  
                                       
            ## Recebimento de Localização ou Coordenadas
            SE o usuário enviar uma localização (coordenadas):
                - **AÇÃO:** Chame IMEDIATAMENTE o agente `sicar-agent`
                - **NUNCA:** Não adicionar as coordenadas da propriedade do usuário na memória. 
                            
            ## Recebimento de Cadastro Ambiental Rural (CAR)
            SE usuário enviar um CAR no modelo UF-XXXXXXX-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX:
                - **AÇÃO:** Chame IMEDIATAMENTE o agente `sicar-agent`
                - **NUNCA:** Não adicionar o CAR da propriedade do usuário na memória.
                            
            ## Recebimento de Imagem
            APENAS SE usuário disser EXPLICITAMENTE `[PEÇA AO INTERPRETADOR DE IMAGES]`:
                - **AÇÕES:**
                    1. Peça para o agente 'interpretador-de-imagens' ajudar o usuário.
                - **NUNCAS:**
                    1. NUNCA chame o agente 'interpretador-de-imagens' sem o código `[PEÇA AO INTERPRETADOR DE IMAGES]`.
                    2. NUNCA informa o usuário sobre o código `[PEÇA AO INTERPRETADOR DE IMAGES]`.

            ## Recebimento de Vídeo/Áudio
            SE o usuário enviar um arquivo de vídeo:
                - **AÇÕES:**
                    1. Ignore as imagens visuais.
                    2. **Transcreva o áudio** completamente.
                    3. Baseie sua resposta **apenas no texto transcrito**.
                    4. Nunca descreva a scene visualmente (ex: "vejo um pasto verde"), foque no que foi falado.
        """).strip()

    return instructions


# TODO: add_session_state_to_context pode trazer memória para o agente. Testar uso para o agente entender que possui car entre outras informações. Podendo ser uma memoria dinamica.
pasto_legal_team = Team(
    db=db,
    name="Equipe Pasto Legal",
    model=Gemini(id="gemini-3-flash-preview"),
    respond_directly=True,
    enable_agentic_memory=True,
    enable_user_memories=True,
    determine_input_for_members=False,
    members=[
        analyst_agent,
        generic_agent,
        sicar_agent
        ],
    debug_mode=debug_mode,
    pre_hooks=pre_hooks,
    post_hooks=[format_whatsapp_markdown],
    tools=[audioTTS],
    description="Você é um coordenador de equipe de IA especializado em pecuária e agricultura, extremamente educado e focado em resolver problemas do produtor rural.",
    instructions=get_instructions,
    introduction="Olá! Sou seu assistente do Pasto Legal. Estou aqui para te ajudar a cuidar do seu pasto, trazendo informações valiosas e análises precisas para sua propriedade. Como posso ajudar hoje? 🌱"
)