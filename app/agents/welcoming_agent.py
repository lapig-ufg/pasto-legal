import textwrap

from agno.agent import Agent
from agno.run import RunContext

from app.configs.config import config
from app.configs.prompts import get_agent_config
from app.tools.tts_tools import generate_speech
from app.tools.onboarding_tools import accept_terms_and_conditions
from app.tools.persona_tools import update_persona_name, update_persona_role


_welcoming_config = get_agent_config("welcoming_agent")

_INSTRUCOES_BASE = _welcoming_config["instructions"].strip().format(
    terms_text=_welcoming_config["terms_text"].strip()
)


def _onboarding_status(session_state: dict) -> str:
    """Bloco de situação injetado no prompt a cada rodada.

    Sem ele o agente lê sempre o mesmo texto e, quando a conversa sai do
    roteiro (o usuário recusa o nome, manda um palavrão), regride para a
    instrução mais enfática do prompt — o aceite dos termos — e pede de
    novo algo que o usuário já fez.
    """
    persona = session_state.get("user_persona") or {}
    aceito = bool(session_state.get("terms_accepted"))
    nome = persona.get("name")
    funcao = persona.get("role")

    if not aceito:
        etapa = "coletar o aceite dos Termos de Uso"
    elif not nome:
        etapa = "coletar o nome"
    elif not funcao:
        etapa = "coletar a função (Produtor ou Técnico)"
    else:
        etapa = "nada pendente — apenas confirme e encerre com cordialidade"

    return textwrap.dedent(f"""\
        <onboarding-status>
        Termos aceitos: {"SIM" if aceito else "NÃO"}
        Nome informado: {nome or "AINDA NÃO"}
        Função informada: {funcao or "AINDA NÃO"}
        ETAPA ATUAL: {etapa}
        </onboarding-status>""")


def get_instructions(run_context: RunContext) -> str:
    session_state = run_context.session_state or {}
    return f"{_onboarding_status(session_state)}\n\n{_INSTRUCOES_BASE}"


welcoming_agent = Agent(
    name=_welcoming_config["name"],
    role=_welcoming_config["role"],
    description=_welcoming_config["description"],
    instructions=get_instructions,
    cache_callables=False,
    tools=[
        generate_speech,
        accept_terms_and_conditions,
        update_persona_name,
        update_persona_role
    ],
    model=config.model,
    fallback_models=[config.fallback_model],
    debug_mode=config.DEBUG_MODE
)