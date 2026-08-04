"""Onboarding gate logic isolated from workflow step composition.

Encapsulates the DB query that determines whether a user has accepted the
terms of service, so the workflow step can stay a thin wrapper.

External interface:
    needs_onboarding(session_state) -- True if the user must go through
        onboarding (terms not yet accepted).
"""

from typing import Any, Dict

from app.core.session_state import WorkflowState
from app.database.models import UserTermsAcceptance
from app.database.session import SessionLocal


def needs_onboarding(session_state: Dict[str, Any]) -> bool:
    """Return True if the user needs to go through onboarding.

    Returns True if the terms have NOT yet been accepted. Lazily initializes
    the ``workflow_state`` slot in ``session_state`` when missing.
    """
    if session_state.get("workflow_state") is None:
        session_state["workflow_state"] = WorkflowState().model_dump()

    if session_state.get("terms_accepted"):
        return False

    user_id = session_state.get("user_id")
    if not user_id:
        return True

    db_session = SessionLocal()
    try:
        record = db_session.query(UserTermsAcceptance).filter(
            UserTermsAcceptance.user_id == user_id,
            UserTermsAcceptance.accepted == True,
        ).first()

        if record:
            session_state["terms_accepted"] = True
            return False

        return True
    finally:
        db_session.close()