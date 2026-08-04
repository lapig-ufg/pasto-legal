"""Summarization step: periodically summarizes conversation history.

Maintains a rolling summary in ``session_state['summary_state']`` so that
later agent steps can prepend the running summary to their input. Runs only
every ``SUMMARY_THRESHOLD`` turns to avoid recomputing each time.

External interface:
    summarization_executor  -- StepExecutor consumed by summarization_workflow.
"""

from typing import Any, Dict, Optional

from agno.utils.log import log_debug, log_error
from agno.workflow.types import StepInput, StepOutput

from app.agents.summary_agent import summary_agent
from app.schemas.input_manager import InputManager


SUMMARY_THRESHOLD = 6
HISTORY_WINDOW = 4


def summarization_executor(
    step_input: StepInput,
    session_state: Dict[str, Any],
) -> Optional[StepOutput]:
    summary_state = InputManager.model_validate(
        session_state.get("summary_state", {})
    )

    if summary_state.runs_count < SUMMARY_THRESHOLD:
        summary_state.runs_count += 1
        session_state["summary_state"] = summary_state.model_dump()
        log_debug(
            f"summarization_executor: skipping (runs_count={summary_state.runs_count})"
        )
        return None

    history_msgs = step_input.get_workflow_history(num_runs=SUMMARY_THRESHOLD)
    if not history_msgs:
        log_debug("summarization_executor: no history available, skipping")
        summary_state.runs_count += 1
        session_state["summary_state"] = summary_state.model_dump()
        return None

    recent_msgs = history_msgs[:HISTORY_WINDOW]

    summary_input = ""
    for idx, msg in enumerate(recent_msgs):
        request_msg, response_msg = msg
        summary_input += (
            f"[Iteração {idx}]\n"
            f"Usuário: {request_msg}\n"
            f"Assistente: {response_msg}\n\n"
        )

    user_msg = step_input.get_input_as_string() or ""
    if user_msg:
        summary_input += f"[Última Iteração]\nUsuário: {user_msg}\n"

    try:
        response = summary_agent.run(
            summary_input,
            session_state=session_state,
        )
    except Exception as exc:
        log_error(f"summarization_executor: agent failed: {exc}")
        summary_state.runs_count += 1
        session_state["summary_state"] = summary_state.model_dump()
        return None

    if response and response.content:
        summary_state.summary = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )
        summary_state.runs_count = 2
    else:
        log_debug("summarization_executor: agent returned empty content")
        summary_state.runs_count += 1

    session_state["summary_state"] = summary_state.model_dump()
    return StepOutput(content="Summary updated")