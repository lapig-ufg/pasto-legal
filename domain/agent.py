"""Pasto Legal domain — dynamic tool selection and instructions.

The domain-specific half of the single agent: registration-state machine
(pending/final/default), property CRUD tools, and pasture-analysis tools.
The neutral shell (model, knowledge, skills, persona/context helpers) lives in
``semente.agents.build_agent``.
"""

import textwrap

from semente.context import Context as RunContext
from semente.tools import Calculator
from semente.logging import log_debug

from semente.agents.build_agent import context_blocks, persona_text
from semente.configs.prompts import get_agent_config
from semente.schemas.user_persona import UserPersona
from semente.tools.tts_tools import generate_speech

from domain.schemas.property_feature import validate_feature_record
from domain.tools.analysis_tools import (
    generate_biomass_image,
    generate_biomass_video,
    generate_pasture_classification_image,
    generate_property_boletim,
    generate_property_image,
    generate_soil_texture_image,
    get_pasture_stats,
    get_topographic_stats,
)
from domain.tools.property_tools import (
    cancel_registration,
    complete_registration,
    confirm_car_selection,
    remove_all_properties,
    remove_property,
    select_car_from_list,
    set_property_name,
    start_registration_by_buffer,
    start_registration_by_car,
    start_registration_by_coordinate,
    start_registration_by_url,
)
from domain.tools.weather_tools import (
    get_daily_precipitation_forecast,
    get_dry_season_onset_forecast,
    get_monthly_precipitation_forecast,
    get_rain_season_onset_forecast,
    get_temperature_forecast,
)

_agent_config = get_agent_config("single_agent")


# ---
# Analyst toolkit is always available so the agent can answer analytical
# questions and run the initial diagnosis regardless of the registration state.
# ---
_ANALYST_TOOLS = [
    Calculator(exclude_tools=["is_prime", "factorial"]),
    get_pasture_stats,
    get_topographic_stats,
    generate_property_image,
    generate_biomass_image,
    generate_biomass_video,
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
            validate_feature_record(prop)
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
            start_registration_by_buffer,
            *_ANALYST_TOOLS
        ])

    return tools


def _registrations_text(session_state) -> str:
    all_properties = [
        validate_feature_record(record)
        for record in session_state.get("all_properties", [])
    ]
    if all_properties:
        return "\n".join(str(record) for record in all_properties)
    return _agent_config["registrations_empty"].strip()


def get_instructions(run_context: RunContext) -> str:
    log_debug("GET INSTRUCTIONS (single_agent)")
    session_state = run_context.session_state or {}
    registration_state = session_state.get("registration_state", None)
    ctx_blocks = context_blocks(session_state)

    # ==========================================
    # ESTADO: PENDING (Confirmação ou Seleção)
    # ==========================================
    if registration_state == "pending":
        candidate_properties = [
            validate_feature_record(prop)
            for prop in session_state.get("candidate_properties", [])
        ]

        # Cenário A: Apenas 1 propriedade encontrada para confirmação
        if len(candidate_properties) == 1:
            candidate_text = str(candidate_properties[0])

            instructions = textwrap.dedent(f"""
                {ctx_blocks}

                {_agent_config['instructions_pending_single'].strip().format(candidate_text=candidate_text)}
            """).strip()

        # Cenário B: Múltiplas propriedades encontradas (Usuário precisa escolher)
        else:
            options_text = []
            for i, prop in enumerate(candidate_properties):
                options_text.append(f"*Opção {i + 1}* - {prop.describe()}")
            candidate_text = "\n".join(options_text)

            instructions = textwrap.dedent(f"""
                {ctx_blocks}

                {_agent_config['instructions_pending_multiple'].strip().format(options_text=candidate_text)}
            """).strip()

    # ==========================================
    # ESTADO: FINAL (Definição de Nome customizado + Diagnóstico inicial)
    # ==========================================
    elif registration_state == "final":
        candidate_properties = [
            validate_feature_record(prop)
            for prop in session_state.get("candidate_properties", [])
        ]
        candidate_text = str(candidate_properties[0]) if candidate_properties else _agent_config["final_candidate_fallback"].strip()

        instructions = textwrap.dedent(f"""
            {ctx_blocks}

            {_agent_config['instructions_final'].strip().format(candidate_text=candidate_text)}
        """).strip()

    # ==========================================
    # ESTADO: DEFAULT / ELSE (Gerenciamento Geral + Análise + Q&A)
    # ==========================================
    else:
        persona = persona_text(session_state)
        registrations_text = _registrations_text(session_state)

        instructions = textwrap.dedent(f"""\
            {ctx_blocks}

            <user-persona>
            {persona}
            </user-persona>

            <registrations>
            {registrations_text}
            </registrations>

            {_agent_config['instructions_default'].strip()}
        """).strip()

    # Hard output contract on every state: the model applies the directive
    # logic silently — it never narrates its reasoning to the user.
    return instructions + "\n\n" + _agent_config["output_contract"].strip()
