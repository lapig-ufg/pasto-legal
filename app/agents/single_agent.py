import textwrap

from agno.agent import Agent
from agno.run import RunContext
from agno.skills import LocalSkills, Skills, SkillValidationError
from agno.tools.calculator import CalculatorTools
from agno.utils.log import log_debug

from app.configs.config import config
from app.configs.prompts import get_agent_config
from app.knowledge.pasto_legal_kb import pasto_legal_kb
from app.schemas.rural_property import RuralProperty
from app.schemas.user_persona import UserPersona
from app.tools.analysis_tools import (
    generate_biomass_image,
    generate_pasture_classification_image,
    generate_property_image,
    generate_property_boletim,
    generate_soil_texture_image,
    get_pasture_stats,
    get_topographic_stats,
)
from app.tools.property_tools import (
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
    get_monthly_precipitation_forecast,
    get_daily_precipitation_forecast,
    get_rain_season_onset_forecast,
    get_dry_season_onset_forecast,
    get_temperature_forecast,
)

try:
    skills = Skills(loaders=[LocalSkills("app/skills/property_analyst_agent")])
except SkillValidationError:
    skills = None

_agent_config = get_agent_config("single_agent")


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
    generate_property_boletim,
    get_monthly_precipitation_forecast,
    get_daily_precipitation_forecast,
    get_rain_season_onset_forecast,
    get_dry_season_onset_forecast,
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
        return _agent_config["persona_fallback"].strip()
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
    return _agent_config["registrations_empty"].strip()


def _context_blocks(session_state) -> str:
    """Build the <history_context> and <conversation_summary> blocks read
    from session_state, to be prepended to the agent instructions.

    - ``history_context``: the dynamic <iterações> block, written by
      ``_input_pre_processing`` (app.core.step_factory) each turn. Grows and
      shrinks dynamically via ``InputManager.runs_count``.
    - ``conversation_summary``: the running summary, written by the
      summarization step each turn.
    """
    parts: list[str] = []

    history_context = session_state.get("history_context") or ""
    if history_context:
        parts.append(f"<history_context>\n{history_context}\n</history_context>")

    conversation_summary = session_state.get("conversation_summary") or ""
    if conversation_summary:
        parts.append(
            f"<conversation_summary>\n{conversation_summary}\n</conversation_summary>"
        )

    return "\n".join(parts)


def get_instructions(run_context: RunContext) -> str:
    log_debug("GET INSTRUCTIONS (single_agent)")
    session_state = run_context.session_state or {}
    registration_state = session_state.get("registration_state", None)
    context_blocks = _context_blocks(session_state)

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
                {context_blocks}

                {_agent_config['instructions_pending_single'].strip().format(candidate_text=candidate_text)}
            """).strip()

        # Cenário B: Múltiplas propriedades encontradas (Usuário precisa escolher)
        else:
            options_text = []
            for i, prop in enumerate(candidate_properties):
                options_text.append(f"*Opção {i + 1}* - {prop.describe()}")
            candidate_text = "\n".join(options_text)

            instructions = textwrap.dedent(f"""
                {context_blocks}

                {_agent_config['instructions_pending_multiple'].strip().format(options_text=candidate_text)}
            """).strip()

    # ==========================================
    # ESTADO: FINAL (Definição de Nome customizado + Diagnóstico inicial)
    # ==========================================
    elif registration_state == "final":
        candidate_properties = [
            RuralProperty.model_validate(prop)
            for prop in session_state.get("candidate_properties", [])
        ]
        candidate_text = str(candidate_properties[0]) if candidate_properties else _agent_config["final_candidate_fallback"].strip()

        instructions = textwrap.dedent(f"""
            {context_blocks}

            {_agent_config['instructions_final'].strip().format(candidate_text=candidate_text)}
        """).strip()

    # ==========================================
    # ESTADO: DEFAULT / ELSE (Gerenciamento Geral + Análise + Q&A)
    # ==========================================
    else:
        persona_text = _persona_text(session_state)
        registrations_text = _registrations_text(session_state)

        instructions = textwrap.dedent(f"""\
            {context_blocks}

            <user-persona>
            {persona_text}
            </user-persona>

            <registrations>
            {registrations_text}
            </registrations>

            {_agent_config['instructions_default'].strip()}
        """).strip()

    return instructions


single_agent = Agent(
    name=_agent_config["name"],
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
    fallback_models=[config.fallback_model],
    add_datetime_to_context=True,
    timezone_identifier="America/Sao_Paulo",
    debug_mode=config.DEBUG_MODE,
)