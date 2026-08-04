"""Onboarding gate step: decides whether the user must go through onboarding.

Thin wrapper over ``app.core.onboarding.needs_onboarding`` that isolates the
DB access from the workflow composition.

External interface:
    _needs_onboarding  -- Condition evaluator consumed by main_workflow.
"""

from typing import Any, Dict

from agno.workflow.types import StepInput

from app.core.onboarding import needs_onboarding as _needs_onboarding_impl


def _needs_onboarding(step_input: StepInput, session_state: Dict[str, Any]) -> bool:
    """Determines whether the user needs to go through onboarding.

    Returns True if the terms have NOT yet been accepted.
    """
    return _needs_onboarding_impl(session_state)