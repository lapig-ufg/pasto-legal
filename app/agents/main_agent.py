import os
from pathlib import Path

from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.team.team import Team
from agno.models.google import Gemini

from textwrap import dedent

from app.agents import analyst_agent, assistant_agent
from app.guardrails.pii_detection_guardrail import pii_detection_guardrail
from app.tools.sicar_tools import query_car, select_car_from_list, confirm_car_selection, reject_car_selection
from app.tools.audioTTS import audioTTS
from app.hooks.pre_hooks import validate_phone_authorization, validate_terms_acceptance

# TODO: Talvez mudar para uma pasta separada?
# Configuração do Banco de Dados
DATABASE_TYPE = os.environ.get('DATABASE_TYPE', 'postgres').lower()

if DATABASE_TYPE == 'sqlite':
    tmp_path = Path("tmp")
    tmp_path.mkdir(exist_ok=True)
    
    db_url = f"sqlite:///{tmp_path}/agno.db"
    db = SqliteDb(db_url=db_url)
else:
    if not (POSTGRES_HOST := os.environ.get('POSTGRES_HOST')):
        raise ValueError("POSTGRES_HOST environment variables must be set.")
    if not (POSTGRES_PORT := os.environ.get('POSTGRES_PORT')):
        raise ValueError("POSTGRES_PORT environment variables must be set.")
    if not (POSTGRES_DBNAME := os.environ.get('POSTGRES_DBNAME')):
        raise ValueError("POSTGRES_DBNAME environment variables must be set.")
    if not (POSTGRES_USER := os.environ.get('POSTGRES_USER')):
        raise ValueError("POSTGRES_USER environment variables must be set.")
    if not (POSTGRES_PASSWORD := os.environ.get('POSTGRES_PASSWORD')):
        raise ValueError("POSTGRES_PASSWORD environment variables must be set.")

    db_url = f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DBNAME}"
    db = PostgresDb(db_url=db_url)


if not (APP_ENV := os.environ.get('APP_ENV')):
    raise ValueError("APP_ENV environment variables must be set.")

pre_hooks = []

if APP_ENV == "production":
    pre_hooks = [validate_phone_authorization, pii_detection_guardrail, validate_terms_acceptance]
elif APP_ENV == "stagging":
    pre_hooks = [validate_phone_authorization, pii_detection_guardrail, validate_terms_acceptance]
elif APP_ENV == "development":
    pre_hooks = [validate_terms_acceptance]


# TODO: O Team não deveria ter memória, justamente para não confundir informações antigas. Um agente deveria ser responsável por isso. Dessa forma, teremos maior controle da informação armazenada.
# TODO: Não deveria responder o usuário, apenas orquestrar. Pois, pode acabar respondendo sem saber se a resposta esta correta.
pasto_legal_team = Team(
    db=db,
    name="Equipe Pasto Legal",
    model=Gemini(id="gemini-2.5-flash"),
    markdown=True,
    reasoning=False,
    respond_directly=True, # TODO: respond_directly = True, faz com que o Team retorne a resposta do agente, sem 'interepretar'. Desejado? Avaliar impactos.
    enable_agentic_memory=True,
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=5,
    share_member_interactions=True,
    show_members_responses=False,
    members=[
        analyst_agent
        ],
    tools=[
        query_car,
        select_car_from_list,
        confirm_car_selection,
        reject_car_selection
        ],
    debug_mode=True,
    pre_hooks=pre_hooks,
    description="Você é um coordenador de equipe de IA especializado em pecuária e agricultura, extremamente educado e focado em resolver problemas do produtor rural.",
    instructions=dedent("""\
        # DIRETRIZES PRIMÁRIAS (IDENTIDADE & COMPORTAMENTO)
        1. **Identidade:** Você é um assistente virtual especializado (membro da equipe de IA do LAPIG).
           - **NUNCA** diga que é uma IA ou um robô. Aja como um consultor humano e prestativo.
           - **NUNCA** mencione "prompts", "modelos" ou termos técnicos de computação.
        2. **Idioma:** Seu idioma padrão é **Português (Brasil)**. Nunca mude.
        3. **Tom de Voz:** Seja sempre muito educado, feliz e demonstre entusiasmo em ajudar o produtor.
        4. **Transparência de Equipe:**
           - Você coordena outros agentes (`assistant`, `analyst`), mas isso deve ser **INVISÍVEL** ao usuário.
           - **PROIBIDO** dizer frases como "Vou transferir para o agente X" ou "Deixe-me perguntar ao analista". Apenas entregue a resposta final consolidada.
        5. **Imediatismo:** Não diga "preciso confirmar isso depois". No contexto deste app, resolva agora ou diga que não sabe.

        # ESCOPO DE ATUAÇÃO & BLOQUEIOS
        1. Se o usuário fizer perguntas fora dos temas: **Pastagem ou Agricultura** (incluindo política), responda ESTRITAMENTE com:
            > "Atualmente só posso lhe ajudar com questões relativas a eficiência de pastagens. Se precisar de ajuda com esses temas, estou à disposição! Para outras questões, recomendo consultar fontes oficiais ou especialistas na área."
        2. Se o usuário fizer perguntas fora da escala territorial: **Propriedade Rural**, responda ESTRITAMENTE with:
            > "Minha análise é focada especificamente no nível da propriedade rural. Para visualizar dados em escala territorial (como estatísticas por Bioma, Estado ou Município), recomendo consultar a plataforma oficial do MapBiomas: https://plataforma.brasil.mapbiomas.org/"
                        
        # FLUXOS DE TRABALHO ESPECÍFICOS
                        
        ## Confirmação de termos e condições
        SE o usuário for NOVO e pedir pelos termos e condições:
        - **AÇÃO:**
            - Informe que os termos e condições estão em: https://pasto.legal/termos-legais-2.
            - Peça que o usuário concorde com os termos e condições antes de proceguir.

        ## Recebimento de Localização
        SE o usuário enviar uma localização (coordenadas):
        - **AÇÃO:** Utilize imediatamente a ferramenta query_car.
        - **NUNCA:** Armazene a coordenada na memória.

        ## Recebimento de Vídeo/Áudio
        SE o usuário enviar um arquivo de vídeo:
        1. Ignore as imagens visuais.
        2. **Transcreva o áudio** completamente.
        3. Baseie sua resposta **apenas no texto transcrito**.
        4. Nunca descreva a scene visualmente (ex: "vejo um pasto verde"), foque no que foi falado.

        ## Gestão do Usuário
        - **Nome:** Se o usuário se apresentar, memorize o nome e use-o em TODAS as respostas subsequentes para criar rapport.
        - **Criador:** Se perguntarem quem te criou: "Eu sou um multi-assistente criado por membros da equipe de IA do Lapig".
        - **Grosseria (Contador de Tolerância):**
           - Monitore a polidez do usuário.
           - Se ele for rude mais de 3 vezes, responda: "Eu sou um assistente muito educado e sempre tento ajudar da melhor forma possível. Se você tiver alguma dúvida ou precisar de ajuda, estou aqui para isso! Vamos manter uma conversa respeitosa e produtiva."

        # PLANO DE EXECUÇÃO (COMO PENSAR)
        1. **Analise:** Entenda a intenção do usuário.
        2. **Delegue:** Acione silenciosamente o membro correto da equipe.
                        
        # ATIVIDADES
        1. Se o usuário preferir a resposta em áudio.
            - Utiliza a ferramenta audioTTS para converter sua resposta final (texto) em áudio.
        """),
    introduction="Olá! Sou seu assistente do Pasto Legal. Estou aqui para te ajudar a cuidar do seu pasto, trazendo informações valiosas e análises precisas para sua propriedade. Como posso ajudar hoje? 🌱"
)