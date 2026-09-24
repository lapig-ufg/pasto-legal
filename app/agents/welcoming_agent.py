from enum import Enum, auto
from typing import Any, Dict, List

from agno.agent import Agent
from agno.run import RunContext

from app.configs.config import config
from app.configs.prompts import get_agent_config
from app.schemas.user_persona import (
    is_persona_complete,
    is_persona_field_informed,
)
from app.tools.tts_tools import generate_speech
from app.tools.onboarding_tools import accept_terms_and_conditions
from app.tools.persona_tools import update_persona_name, update_persona_role


_welcoming_config = get_agent_config("welcoming_agent")

_TERMS_INSTRUCTION = _welcoming_config["instructions"].strip().format(
    terms_text=_welcoming_config["terms_text"].strip()
)

_PERSONA_INSTRUCTION = _welcoming_config["instructions_persona"].strip()

_PERSONA_NOT_INFORMED = _welcoming_config["persona_not_informed"].strip()


class OnboardingStatus(Enum):
    NOT_ACCEPTED_TERMS = auto()
    NOT_INFORMED_PERSONA = auto()
    COMPLETE = auto()


def _get_onboarding_status(session_state: Dict[str, Any]) -> OnboardingStatus:
    """Decide which onboarding stage the user is currently on.

    Reads ``terms_accepted`` and ``user_persona`` (a plain dict) from the
    session state and drives both the instructions and the toolset: the terms
    prompt/tool only while the terms are pending, the persona prompt/tools
    only while name or role are missing. Completeness is judged with the
    shared ``is_persona_complete`` rule, so it can never drift from the
    workflow gate.
    """
    if not session_state.get("terms_accepted", False):
        return OnboardingStatus.NOT_ACCEPTED_TERMS

    if not is_persona_complete(session_state.get("user_persona")):
        return OnboardingStatus.NOT_INFORMED_PERSONA

    return OnboardingStatus.COMPLETE


def _get_tools(run_context: RunContext) -> List:
    session_state = run_context.session_state or {}
    onboarding_status = _get_onboarding_status(session_state=session_state)

    tools = [generate_speech]

    if onboarding_status == OnboardingStatus.NOT_ACCEPTED_TERMS:
        tools.extend([accept_terms_and_conditions])

    if onboarding_status == OnboardingStatus.NOT_INFORMED_PERSONA:
        tools.extend([update_persona_name, update_persona_role])

    return tools


def get_instructions(run_context: RunContext) -> str:
    session_state = run_context.session_state or {}
    onboarding_status = _get_onboarding_status(session_state=session_state)

    if onboarding_status == OnboardingStatus.NOT_ACCEPTED_TERMS:
        return _TERMS_INSTRUCTION

    if onboarding_status == OnboardingStatus.NOT_INFORMED_PERSONA:
        user_persona = session_state.get("user_persona") or {}

        user_name = user_persona.get("name")
        user_role = user_persona.get("role")

        if not is_persona_field_informed(user_name):
            user_name = _PERSONA_NOT_INFORMED
        if not is_persona_field_informed(user_role):
            user_role = _PERSONA_NOT_INFORMED

        return _PERSONA_INSTRUCTION.format(user_name=user_name, user_role=user_role)

    # Onboarding complete: the workflow gate routes these users away from the
    # welcoming agent, so there is no instruction to give.
    return ""


welcoming_agent = Agent(
    name=_welcoming_config["name"],
    role=_welcoming_config["role"],
    description=_welcoming_config["description"],
    instructions=get_instructions,
    cache_callables=False,
    tools=_get_tools,
    model=config.model,
    fallback_models=[config.fallback_model],
    debug_mode=config.DEBUG_MODE
)