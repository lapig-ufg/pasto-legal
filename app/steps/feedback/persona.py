"""Persona management step: conditionally updates the user persona.

Calls the persona manager agent only when:
- satisfaction level >= 2, OR
- satisfaction level < 2 AND remediation effectiveness > 3

The agent returns a PersonaUpdate with preferences (and optionally name,
role, regionality) to change. The executor applies those changes directly
to session_state['user_persona'].

After applying updates (or skipping), clears user_mood from session_state.

External interface:
    manage_persona  -- StepExecutor consumed by feedback_workflow.
"""

from typing import Any, Dict

from agno.utils.log import log_error
from agno.workflow.types import StepInput, StepOutput

from app.agents.persona_agent import persona_manager_agent
from app.schemas.user_mood import UserMood
from app.schemas.user_persona import (
    CommunicationPreference,
    PersonaUpdate,
    UserPersona,
)


def manage_persona(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Conditionally run the persona manager agent and apply persona updates."""
    raw_user_mood = session_state.get("user_mood", None)
    if raw_user_mood is None:
        return

    user_mood = UserMood.model_validate(raw_user_mood)

    if (
        user_mood.satisfaction.level < 3 and
        user_mood.remediation and
        user_mood.remediation.effectiveness
        and user_mood.remediation.effectiveness.level < 4
        ):
        return

    user_msg = step_input.get_input_as_string() or ""
    try:
        response = persona_manager_agent.run(
            user_msg,
            session_state={"user_mood": user_mood},
        )
        if response and response.content:
            # Parse the PersonaUpdate from the agent's response
            persona_update = response.content
            if isinstance(persona_update, dict):
                persona_update = PersonaUpdate.model_validate(persona_update)

            # Apply updates to session_state["user_persona"]
            current_persona = session_state.get("user_persona", {})
            user_persona = (
                UserPersona.model_validate(current_persona) if current_persona else UserPersona()
            )

            # Apply scalar field updates (only if non-None)
            if persona_update.name is not None:
                user_persona.name = persona_update.name
            if persona_update.role is not None:
                user_persona.role = persona_update.role
            if persona_update.regionality is not None:
                user_persona.regionality = persona_update.regionality

            # Apply preference updates (add new, update existing)
            existing_prefs = {p.key: i for i, p in enumerate(user_persona.communication_preferences)}
            for new_pref in persona_update.communication_preferences:
                normalized_key = new_pref.key.strip().lower()
                if normalized_key in existing_prefs:
                    idx = existing_prefs[normalized_key]
                    user_persona.communication_preferences[idx] = CommunicationPreference(
                        key=normalized_key,
                        description=new_pref.description,
                    )
                else:
                    user_persona.communication_preferences.append(CommunicationPreference(
                        key=normalized_key,
                        description=new_pref.description,
                    ))
                    existing_prefs[normalized_key] = len(user_persona.communication_preferences) - 1

            session_state["user_persona"] = user_persona.model_dump()

        session_state["user_mood"] = None

    except Exception as e:
        log_error(f"manage_persona: agent failed: {e}")