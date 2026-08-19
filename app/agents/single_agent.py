import textwrap

from agno.agent import Agent
from agno.run import RunContext
from agno.skills import LocalSkills, Skills, SkillValidationError
from agno.tools.calculator import CalculatorTools
from agno.utils.log import log_debug

from app.configs.config import config
from app.knowledge.pasto_legal_kb import pasto_legal_kb
from app.schemas.rural_property import RuralProperty
from app.schemas.user_persona import UserPersona
from app.tools.property_analyst_tools import (
    generate_biomass_image,
    generate_pasture_classification_image,
    generate_property_image,
    generate_soil_texture_image,
    get_pasture_stats,
    get_topographic_stats,
)
from app.tools.property_crud_tools import (
    cancel_registration,
    complete_registration,
    confirm_car_selection,
    remove_all_properties,
    remove_property,
    select_car_from_list,
    set_property_name,
    start_registration_by_car,
    start_registration_by_coordinate,
    start_registration_by_url,
)
from app.tools.tts_tools import generate_speech
from app.tools.weather_tools import (
    get_precipitation_forecast,
    get_temperature_forecast,
)

try:
    skills = Skills(loaders=[LocalSkills("app/skills/property_analyst_agent")])
except SkillValidationError:
    skills = None


# ---
# Analyst toolkit is always available so the agent can answer analytical
# questions and run the initial diagnosis regardless of the registration state.
# ---
_ANALYST_TOOLS = [
    CalculatorTools(exclude_tools=["is_prime", "factorial"]),
    get_pasture_stats,
    get_topographic_stats,
    generate_property_image,
    generate_biomass_image,
    generate_soil_texture_image,
    generate_pasture_classification_image,
    get_precipitation_forecast,
    get_temperature_forecast,
]


def get_tools(run_context: RunContext):
    session_state = run_context.session_state
    registration_state = session_state.get("registration_state", None)

    tools = [generate_speech]

    # ==========================================
    # ESTADO: PENDING (Confirmação ou Seleção)
    # ==========================================
    if registration_state == "pending":
        candidate_properties = [
            RuralProperty.model_validate(prop)
            for prop in session_state.get("candidate_properties", [])
        ]

        # Cenário A: Apenas 1 propriedade encontrada para confirmação
        if len(candidate_properties) == 1:
            tools.extend([confirm_car_selection, cancel_registration])

        # Cenário B: Múltiplas propriedades encontradas (Usuário precisa escolher)
        tools.extend([select_car_from_list, cancel_registration])

    # ==========================================
    # ESTADO: FINAL (Definição de Nome customizado)
    # ==========================================
    elif registration_state == "final":
        tools.extend([complete_registration, get_pasture_stats, cancel_registration])

    # ==========================================
    # ESTADO: DEFAULT / ELSE (Gerenciamento Geral)
    # ==========================================
    else:
        tools.extend([
            remove_property,
            remove_all_properties,
            set_property_name,
            start_registration_by_url,
            start_registration_by_car,
            start_registration_by_coordinate,
            *_ANALYST_TOOLS
        ])

    return tools


def _persona_text(session_state) -> str:
    user_persona = session_state.get("user_persona", None)
    if user_persona is None:
        return (
            "Perfil geral: Produtor rural ou parceiro do Pasto Legal. "
            "Adote um tom acolhedor e respeitoso do campo."
        )
    try:
        if isinstance(user_persona, dict):
            user_persona = UserPersona.model_validate(user_persona)
        return str(user_persona)
    except Exception:
        return str(user_persona)


def _registrations_text(session_state) -> str:
    all_properties = [
        RuralProperty.model_validate(record)
        for record in session_state.get("all_properties", [])
    ]
    if all_properties:
        return "\n".join(str(record) for record in all_properties)
    return "*Nenhum imóvel cadastrado no momento.*"


def get_instructions(run_context: RunContext) -> str:
    log_debug("GET INSTRUCTIONS (single_agent)")
    session_state = run_context.session_state or {}
    registration_state = session_state.get("registration_state", None)

    # ==========================================
    # ESTADO: PENDING (Confirmação ou Seleção)
    # ==========================================
    if registration_state == "pending":
        candidate_properties = [
            RuralProperty.model_validate(prop)
            for prop in session_state.get("candidate_properties", [])
        ]

        # Cenário A: Apenas 1 propriedade encontrada para confirmação
        if len(candidate_properties) == 1:
            candidate_text = str(candidate_properties[0])

            instructions = textwrap.dedent(f"""
                # Perfil e Objetivo
                Você é o Gestor de Propriedades Rurais do sistema Pasto Legal. Sua função atual é estritamente coletar a confirmação do usuário para o imóvel rural encontrado.

                # Propriedade em Análise
                O sistema localizou a seguinte propriedade para o usuário:
                > {candidate_text}

                # Diretrizes de Execução
                - Se o usuário confirmar que esta é a propriedade correta (ex: "sim", "essa mesma", "pode salvar"), acione imediatamente a ferramenta `confirm_car_selection`.
                - Se o usuário rejeitar a propriedade (ex: "não é essa", "está errado"), acione a ferramenta `cancel_registration`.
                - Ignore assuntos paralelos. Se o usuário tentar mudar de assunto, traga-o de volta educadamente para a confirmação do imóvel.
            """).strip()

        # Cenário B: Múltiplas propriedades encontradas (Usuário precisa escolher)
        else:
            options_text = []
            for i, prop in enumerate(candidate_properties):
                options_text.append(f"*Opção {i + 1}* - {prop.describe()}")
            candidate_text = "\n".join(options_text)

            instructions = textwrap.dedent(f"""
                # Perfil e Objetivo
                Você é o Gestor de Propriedades Rurais do sistema Pasto Legal. Múltiplos imóveis foram encontrados e o usuário precisa selecionar um deles.

                # Opções Disponíveis
                {candidate_text}

                # Diretrizes de Execução
                - Se o usuário escolher uma das opções (pelo número, nome ou índice), invoque a ferramenta `select_car_from_list` passando o parâmetro correspondente.
                - Se o usuário desistir ou disser que nenhuma serve, acione a ferramenta `cancel_registration`.
                - Se ele demonstrar confusão, instrua-o de forma simples a digitar apenas o número da opção desejada.
            """).strip()

    # ==========================================
    # ESTADO: FINAL (Definição de Nome customizado + Diagnóstico inicial)
    # ==========================================
    elif registration_state == "final":
        candidate_properties = [
            RuralProperty.model_validate(prop)
            for prop in session_state.get("candidate_properties", [])
        ]
        candidate_text = str(candidate_properties[0]) if candidate_properties else "Propriedade selecionada"

        instructions = textwrap.dedent(f"""
            # Perfil e Objetivo
            Você está na etapa final de cadastro do imóvel rural:
            > {candidate_text}

            Sua missão é coletar ou definir um nome amigável para esta propriedade e, em seguida, entregar o primeiro diagnóstico.

            # Diretrizes de Execução
            - Se o usuário informar um nome para a propriedade (ex: "Quero que se chame Fazenda Primavera"), invoque imediatamente a ferramenta `complete_registration` passando esse nome.
            - Ao receber o retorno de `complete_registration`, siga ESTRITAMENTE a instrução contida nele: chame `get_pasture_stats` com o CAR da propriedade e entregue ao usuário um diagnóstico acolhedor em UM único parágrafo contínuo (2 a 3 frases fluidas, sem bullet points), citando no máximo 1 ou 2 dados reais, com 1 ou 2 emojis discretos no final e finalizando com UMA única pergunta-CTA sobre capacidade de suporte ou manejo.
            - Se o usuário desejar abortar o processo nesta fase, chame a ferramenta `cancel_registration`.
            - Se o usuário não fornecer um nome claro ou enviar saudações vagas, lembre-o de que ele precisa dar um nome para concluir ou digitar "cancelar".
            - Mantenha o texto limpo, curto e focado em mensagens de celular (`*texto*` para negrito).
        """).strip()

    # ==========================================
    # ESTADO: DEFAULT / ELSE (Gerenciamento Geral + Análise + Q&A)
    # ==========================================
    else:
        persona_text = _persona_text(session_state)
        registrations_text = _registrations_text(session_state)

        instructions = textwrap.dedent(f"""\
            <user-persona>
            {persona_text}
            </user-persona>

            <registrations>
            {registrations_text}
            </registrations>

            # Perfil e Objetivo
            Você é o assistente oficial do Pasto Legal. Cumpre três papéis integrados:
            1. **Gestor de Propriedades Rurais**: iniciar novos cadastros, listar e remover imóveis, atribuir nomes.
            2. **Agente Extensionista Agrônomo**: analisar pastagens, gerar mapas/imagens e dar insights com base em cartilhas da Embrapa.
            3. **Guia de Suporte (Q&A)**: responder dúvidas conceituais e de uso da plataforma.

            # Regras de Análise (Extensionista)
            - Sempre informe o ano de referência das análises.
            - Seja o mais conciso possível, explicando os resultados de forma simples.
            - Use seu conhecimento com base em cartilhas e conhecimentos da Embrapa para esclarecer dúvidas dos usuários.
            - Gere imagens apenas quando explicitamente pedido pelo usuário.
            - Gere apenas um tipo de imagem por vez. Nunca gere mais de um tipo de imagem por vez.

            # Regras de Suporte (Q&A)
            - Responda baseando-se EXCLUSIVAMENTE nos trechos retornados pela base de conhecimento.
            - Seja simples e didático, explicando os passos de forma simples para o pequeno produtor rural.

            # Formato e Escopo de Atuação
            - **Comunicação (WhatsApp):** Respostas curtas, objetivas. Use markdown no formato do WhatsApp. Não use bullet points.
            - **Âmbito principal:** Você é especialista em **Agropecuária** e áreas correlatas (solos, pastagens, manejo, geotecnologias aplicadas ao campo). Direcione a conversa para esse tema sempre que possível.
            - **Escala territorial:** Suas análises e ferramentas operam no nível da **Propriedade Rural**. Quando o usuário perguntar sobre escalas maiores (município, estado, bioma), explique que sua atuação é no nível da propriedade e ofereça o que pode fazer por ele dentro dela.
            - **Perguntas conversacionais simples** (saudações, "quem é você?", "quantos de vocês são?", "quem te criou?"): responda de forma natural, breve e acolhedora, como um atendente faria — sem desviar para o escopo técnico.
            - **Dúvidas sobre a plataforma ("como fazer", "o que significa", funcionalidades):** use a ferramenta de busca da base de conhecimento (`search_knowledge_base`) e responda com base nos trechos retornados.
            - **Pedidos de dados/análises que você não tem ferramentas para gerar:** reconheça a ideia de forma positiva e sugira o que você consegue fazer hoje dentro do tema (ex: "Que ideia legal! Hoje consigo te ajudar com X, Y e Z — quer que eu mostre?").
        """).strip()

    return instructions


single_agent = Agent(
    name="Pasto Legal",
    tools=get_tools,
    markdown=True,
    use_instruction_tags=False,
    instructions=get_instructions,
    cache_callables=False,
    knowledge=pasto_legal_kb,
    search_knowledge=True,
    add_search_knowledge_instructions=True,
    skills=skills,
    model=config.model,
    debug_mode=config.DEBUG_MODE,
)