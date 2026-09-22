"""Onboarding gate: decides whether the user still needs to identify themselves.

Kept in its own module, apart from `pasto_legal_workflow`, so the decision rule
can be imported (and tested) without pulling in the agents, the knowledge base
and the embedder that the workflow composition needs. This file must depend
only on the database models and the session factory.

External interface:
    _needs_onboarding  -- evaluator consumed by the `Onboarding Check` Condition.
"""

from typing import Any

from agno.workflow.types import StepInput

from app.database.models import UserProfile, UserTermsAcceptance
from app.database.session import SessionLocal
from app.schemas.workflow_state import WorkflowState


def _needs_onboarding(step_input: StepInput, session_state: dict[str, Any]) -> bool:
    """Return True if the user still needs to go through onboarding.

    Onboarding covers two things: the formal acceptance of the terms and the
    identification profile (name + role). Both are looked up in the database, so
    a user who already completed them is never asked again — not even in a
    brand new session. On the way out, the stored profile is copied into
    ``session_state`` so the agent can personalise from the first reply.
    """
    if session_state.get("workflow_state") is None:
        session_state["workflow_state"] = WorkflowState().model_dump()

    persona = session_state.get("user_persona") or {}
    if session_state.get("terms_accepted") and persona.get("name") and persona.get("role"):
        return False

    workflow_session = getattr(step_input, "workflow_session", None)
    user_id = getattr(workflow_session, "user_id", None) or session_state.get("user_id")
    if not user_id:
        return True

    db_session = SessionLocal()
    try:
        if not session_state.get("terms_accepted"):
            aceite = db_session.query(UserTermsAcceptance).filter(
                UserTermsAcceptance.user_id == user_id,
                UserTermsAcceptance.accepted == True,
            ).first()

            if not aceite:
                return True

            session_state["terms_accepted"] = True

        perfil = db_session.query(UserProfile).filter(
            UserProfile.user_id == user_id
        ).first()

        if perfil is None or not perfil.name or not perfil.role:
            return True

        persona.setdefault("name", perfil.name)
        persona.setdefault("role", perfil.role)
        session_state["user_persona"] = persona

        return False
    finally:
        db_session.close()
