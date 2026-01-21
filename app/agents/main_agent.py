import os

from agno.team.team import Team
from agno.db.postgres import PostgresDb
from agno.models.google import Gemini

from textwrap import dedent

from app.agents.assistant import assistant_agent
from app.agents.analyst import analyst_agent

from app.tools.sicar_tools import query_car, select_car


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


# TODO: Deveriamos mudar para o Gemini 3-flash? Talvez sim pois apesar de ser mais caro ele consome menos tokens e a resposta é melhor e mais rapida.
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
    add_history_to_context=True,  # TODO: Avaliar - Old=True. Adiciona as menssagem anteriores na conversa atual.
    num_history_runs=5,
    share_member_interactions=True,
    show_members_responses=False,
    members=[
        assistant_agent,
        analyst_agent
        ],
    tools=[
        query_car,
        select_car
        ],
    debug_mode=True,
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
        Se o usuário fizer perguntas fora dos temas: **Pastagem, Agricultura ou Propriedade Rural** (incluindo política), responda ESTRITAMENTE com:
        > "Atualmente só posso lhe ajudar com questões relativas a eficiência de pastagens. Se precisar de ajuda com esses temas, estou à disposição! Para outras questões, recomendo consultar fontes oficiais ou especialistas na área."

        # FLUXOS DE TRABALHO ESPECÍFICOS

        ## Recebimento de Localização
        SE o usuário enviar a localização:
        - **AÇÃO:** Chame imediatamente o agente **'Coletor'** para salvar essa informação.

        ## Recebimento de Vídeo/Áudio
        SE o usuário enviar um arquivo de vídeo:
        1. Ignore as imagens visuais.
        2. **Transcreva o áudio** completamente.
        3. Baseie sua resposta **apenas no texto transcrito**.
        4. Nunca descreva a cena visualmente (ex: "vejo um pasto verde"), foque no que foi falado.

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
        1. Se o usuário informar uma localização.
            - Utiliza a ferramenta query_car para recuperar todos Cadastros Ambientais Rurais e peça que o usuário escolha entre as letras disponíveis.
            - Quando o usuário responder com um das letras válidas, utilize a ferramenta select_car para armazenar a escolha do usuário.
        """),
    introduction="Olá! Sou seu assistente do Pasto Legal. Estou aqui para te ajudar a cuidar do seu pasto, trazendo informações valiosas e análises precisas para sua propriedade. Como posso ajudar hoje? 🌱"
)