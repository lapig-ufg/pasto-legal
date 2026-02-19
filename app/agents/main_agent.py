import os
import textwrap

from agno.run import RunContext
from agno.team.team import Team
from agno.models.google import Gemini

from app.agents import analyst_agent, generic_agent
from app.guardrails.pii_detection_guardrail import pii_detection_guardrail
from app.tools.sicar_tools import query_car, select_car_from_list, confirm_car_selection, reject_car_selection
from app.hooks.pre_hooks import validate_phone_authorization
from app.hooks.post_hooks import format_whatsapp_markdown
from app.database.database import db


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

    is_confirming_car = session_state.get("is_confirming_car", False)
    is_selecting_car = session_state.get("is_selecting_car", False)

    # TODO: Implementar uma linha de instruções para usuários novos aceitarem os termos e condições.

    if is_confirming_car:
        instructions = textwrap.dedent("""
            Atue exclusivamente na etapa de confirmação de Cadastro Ambiental Rural (CAR).
            Regras:
                1. Acione a ferramenta confirm_car_selection ou reject_car_selection com base na resposta.
                2. Ignore assuntos paralelos. Se o usuário fugir do tema, redirecione-o educadamente para a seleção do imóvel rural.
                3. Se o usuário estiver confuso, instrua-o a confirmar ou rejeitar CAR ou a cancelar a operação.
                4. Recuse educadamente toda solicitação até que o usuário selecione, recuse ou cancele a operação.
                5. NUNCA acione membros e agentes.
        """).strip()
    if is_selecting_car:
        instructions = textwrap.dedent("""
            Atue exclusivamente na etapa de seleção de Cadastro Ambiental Rural (CAR).
            Regras:
                1. Acione a ferramenta select_car_from_list ou reject_car_selection com base na resposta.
                2. Ignore assuntos paralelos. Se o usuário fugir do tema, redirecione-o educadamente para a seleção do imóvel rural.
                3. Se o usuário estiver confuso, instrua-o a digitar o número correspondente ao CAR desejado ou a cancelar a operação.
                4. Recuse educadamente toda solicitação até que o usuário confirme, recuse ou cancele a operação.
                5. NUNCA acione membros e agentes.
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
            6. **Conhecimento:** Assuma SEMPRE que o sistema possui todas as informações necessárias para execução.
            7. **Markdown:** Evite markdown. MAS, se usar markdown garanta estar no fomato do WhatsApp.

            # BLOQUEIOS
            1. Se o usuário fizer perguntas fora dos temas: **Pastagem, Agricultura, Uso e Cobertura da Terra e afins** (incluindo política), responda ESTRITAMENTE com:
                > "Atualmente só posso lhe ajudar com questões relativas a eficiência de pastagens. Se precisar de ajuda com esses temas, estou à disposição! Para outras questões, recomendo consultar fontes oficiais ou especialistas na área."
            2. Se o usuário fizer perguntas fora da ESCALA TERRITORIAL: **Propriedade Rural**, responda ESTRITAMENTE com:
                > "Minha análise é focada especificamente no nível da propriedade rural. Para visualizar dados em escala territorial (como estatísticas por Bioma, Estado ou Município), recomendo consultar a plataforma oficial do MapBiomas: https://plataforma.brasil.mapbiomas.org/"
                        
            # FLUXOS DE TRABALHO ESPECÍFICOS

            ## Recebimento de Localização ou Coordenadas
            SE o usuário enviar uma localização (coordenadas):
            - **AÇÃO:** Utilize IMEDIATAMENTE a ferramenta query_car.
            - **NUNCA:** Armazene a coordenada na memória.
                            
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
# TODO: O Team não deveria ter memória, justamente para não confundir informações antigas. Um agente deveria ser responsável por isso. Dessa forma, teremos maior controle da informação armazenada.
pasto_legal_team = Team(
    db=db,
    name="Equipe Pasto Legal",
    model=Gemini(id="gemini-3-flash-preview"),
    respond_directly=True,
    enable_agentic_memory=True,
    enable_user_memories=True,
    add_history_to_context=True,
    determine_input_for_members=True,
    num_history_runs=5,
    members=[
        analyst_agent,
        generic_agent
        ],
    tools=[
        query_car,
        select_car_from_list,
        confirm_car_selection,
        reject_car_selection
        ],
    debug_mode=debug_mode,
    pre_hooks=pre_hooks,
    post_hooks=[format_whatsapp_markdown],
    description="Você é um coordenador de equipe de IA especializado em pecuária e agricultura, extremamente educado e focado em resolver problemas do produtor rural.",
    instructions=get_instructions,
    introduction="Olá! Sou seu assistente do Pasto Legal. Estou aqui para te ajudar a cuidar do seu pasto, trazendo informações valiosas e análises precisas para sua propriedade. Como posso ajudar hoje? 🌱"
)