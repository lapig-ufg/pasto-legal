"""Onboarding gate: decides whether the user still needs to identify themselves.

Kept in its own module, apart from `pasto_legal_workflow`, so the decision rule
can be imported (and tested) without pulling in the agents, the knowledge base
and the embedder that the workflow composition needs. This file must depend
only on the database models, the session factory and the persona schema.

External interface:
    _needs_onboarding  -- evaluator consumed by the `Onboarding Check` Condition.
"""

from typing import Any

from agno.workflow.types import StepInput

from app.database.models import UserProfile, UserTermsAcceptance
from app.database.session import SessionLocal
from app.schemas.user_persona import is_persona_complete, is_persona_field_informed
from app.schemas.workflow_state import WorkflowState


def _needs_onboarding(step_input: StepInput, session_state: dict[str, Any]) -> bool:
    """Return True if the user still needs to go through onboarding.

    Onboarding covers the formal acceptance of the terms and the
    identification profile (name + role). Both are resolved from
    ``session_state`` when present and only looked up in the database for the
    parts still missing, so a user who already completed them is never asked
    again — not even in a brand new session. On the way out, the stored
    profile is copied into ``session_state`` so the agent can personalise from
    the first reply.

    The completeness rule (``is_persona_complete``) is shared with the
    welcoming agent, so the gate and the agent can never disagree on whether
    the user's identification is done.
    """
    if session_state.get("workflow_state") is None:
        session_state["workflow_state"] = WorkflowState().model_dump()

    terms_accepted = bool(session_state.get("terms_accepted"))
    persona = session_state.get("user_persona") or {}

    if terms_accepted and is_persona_complete(persona):
        return False

    workflow_session = getattr(step_input, "workflow_session", None)
    user_id = getattr(workflow_session, "user_id", None) or session_state.get("user_id")
    if not user_id:
        return True

    db_session = SessionLocal()
    try:
        if not terms_accepted:
            aceite = db_session.query(UserTermsAcceptance).filter(
                UserTermsAcceptance.user_id == user_id,
                UserTermsAcceptance.accepted == True,
            ).first()

            if not aceite:
                return True

            session_state["terms_accepted"] = True

        if not is_persona_complete(persona):
            perfil = db_session.query(UserProfile).filter(
                UserProfile.user_id == user_id
            ).first()

            if perfil is None:
                return True

            # Fill only the fields still missing (or still holding the schema
            # sentinel), preserving values the agent just wrote this session.
            for field in ("name", "role"):
                if not is_persona_field_informed(persona.get(field)) and getattr(perfil, field):
                    persona[field] = getattr(perfil, field)

            session_state["user_persona"] = persona

        return not is_persona_complete(session_state.get("user_persona") or {})
    finally:
        db_session.close()
