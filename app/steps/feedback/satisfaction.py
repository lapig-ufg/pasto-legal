"""Satisfaction evaluation step and feedback branch selector.

Runs the satisfaction evaluation agent on the user's message and stores the
result in ``session_state['user_mood']``. On the first evaluation, stores
the result under 'satisfaction'; on subsequent evaluations (after
remediation), stores under 'remediation'.

The branch selector picks which feedback persistence branch to follow based
on the satisfaction level.

External interface:
    evaluate_satisfaction        -- StepExecutor consumed by feedback_workflow.
    satisfaction_branch_selector -- Router selector consumed by feedback_workflow.
"""

from typing import Any, Dict, Optional

from agno.utils.log import log_debug, log_error
from agno.workflow.types import StepInput, StepOutput

from app.agents.feedback_agent import satisfaction_evaluation_agent


# Default fallback satisfaction level when the evaluation agent fails.
_DEFAULT_SATISFACTION = {"level": 3, "level_message": "Neutral (default)"}


def evaluate_satisfaction(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Run the satisfaction evaluation agent on the user's message and
    store the result in session_state['user_mood'].
    """
    user_msg = step_input.get_input_as_string() or ""
    history_data = step_input.get_workflow_history(num_runs=1)
    user_mood = session_state.get("user_mood", None)

    effectiveness: Optional[Dict[str, Any]] = None

    try:
        evaluator_msg = ""
        if history_data:
            last_user_msg, last_workflow_response = history_data[0]
            evaluator_msg += "### Last Interaction ###\n"
            evaluator_msg += f"Last user message: {last_user_msg}\n\n"
            evaluator_msg += f"Last workflow response: {last_workflow_response}\n\n"
        evaluator_msg += f"Current user message: {user_msg}\n"

        response = satisfaction_evaluation_agent.run(
            evaluator_msg, session_state={"user_mood": user_mood}
        )
        if response and response.content:
            effectiveness = response.content.model_dump()
    except Exception as e:
        log_error(f"evaluate_satisfaction: agent failed: {e}")

    if effectiveness is None:
        log_debug("evaluate_satisfaction: no effectiveness result, using default")
        effectiveness = _DEFAULT_SATISFACTION.copy()

    if user_mood is None:
        session_state["user_mood"] = {}
        session_state["user_mood"]["satisfaction"] = effectiveness
    else:
        session_state["user_mood"]["remediation"] = effectiveness

    level = effectiveness.get("level", 3)
    level_message = effectiveness.get("level_message", "unknown")
    return StepOutput(
        content=f"The user satisfaction was evaluated as {level} ({level_message})."
    )


def satisfaction_branch_selector(step_input: StepInput, session_state: Dict[str, Any]) -> list:
    """Router selector that determines which feedback branch to follow
    based on the user's satisfaction level.
    """
    user_mood = session_state.get("user_mood", {})
    if not user_mood:
        return ["Neutral"]

    satisfaction = user_mood.get("satisfaction", {})
    satisfaction_level = satisfaction.get("level", 3)

    if satisfaction_level == 5:
        return ["Persist Positive Feedback"]
    elif satisfaction_level == 1:
        remediation = user_mood.get("remediation", {})
        effectiveness = (
            remediation.get("effectiveness", {})
            if isinstance(remediation, dict)
            else {}
        )
        if not effectiveness or effectiveness.get("level", 2) <= 2:
            return ["Persist Negative Feedback"]

    return ["Neutral"]