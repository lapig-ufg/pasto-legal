"""Feedback persistence and the final merge step.

These steps run after the parallel branches complete: they read the normal
agent response, persist frustrated/amazed interactions to the DB for future
fine-tuning, and merge the evaluation branch with the normal response.
"""
from typing import Any, Dict
from datetime import datetime

from agno.run import RunContext
from agno.workflow.types import StepInput, StepOutput
from agno.utils.log import log_error, log_debug

from app.database.session import SessionLocal, engine
from app.database.models import FrustrationFeedback, PositiveFeedback
from app.tools.feedback_tools import _mask_pii


def _get_normal_response(step_input: StepInput) -> str:
    """Pull the normal agent execution output from the parallel branch."""
    content = step_input.get_step_content("normal_response")
    if isinstance(content, dict):
        # Parallel aggregates as {step_name: content}; grab the value if so.
        content = next(iter(content.values())) if content else ""
    return content or ""


def save_frustration(
    step_input: StepInput,
    session_state: Dict[str, Any],
    run_context: RunContext = None,
) -> StepOutput:
    """Persist a frustrated interaction to the FrustrationFeedback table."""
    grade = session_state.get("satisfaction_grade", 3)
    user_msg = step_input.get_input_as_string() or ""
    normal_response = _get_normal_response(step_input)
    handler_msg = session_state.get("handler_message", "")

    FrustrationFeedback.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        novo_feedback = FrustrationFeedback(
            timestamp=datetime.now().isoformat(),
            original_question=_mask_pii(user_msg),
            reason_frustration=f"auto low satisfaction grade={grade}",
            desired_answer=_mask_pii(normal_response),
            context=_mask_pii(handler_msg),
        )
        session.add(novo_feedback)
        session.commit()
        log_debug("Frustration feedback saved by workflow.")
    except Exception as e:
        session.rollback()
        log_error(f"Erro ao registrar frustration feedback: {e}")
    finally:
        session.close()

    return StepOutput(content="frustration_saved")


def save_amazed(
    step_input: StepInput,
    session_state: Dict[str, Any],
    run_context: RunContext = None,
) -> StepOutput:
    """Persist an amazed interaction to the PositiveFeedback table for future fine-tuning."""
    grade = session_state.get("satisfaction_grade", 3)
    user_msg = step_input.get_input_as_string() or ""
    normal_response = _get_normal_response(step_input)
    handler_msg = session_state.get("handler_message", "")

    PositiveFeedback.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        novo_feedback = PositiveFeedback(
            timestamp=datetime.now().isoformat(),
            user_message=_mask_pii(user_msg),
            assistant_response=_mask_pii(normal_response),
            handler_message=_mask_pii(handler_msg),
            grade=grade,
            context=_mask_pii(normal_response),
        )
        session.add(novo_feedback)
        session.commit()
        log_debug("Positive feedback saved by workflow.")
    except Exception as e:
        session.rollback()
        log_error(f"Erro ao registrar positive feedback: {e}")
    finally:
        session.close()

    return StepOutput(content="amazed_saved")


def merge_response(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Merge the evaluation branch with the normal agent response.

    If the user was frustrated (grade < 3), prepend an apology and offer a
    better response. Otherwise, proceed with the normal agent response.
    """
    grade = session_state.get("satisfaction_grade", 3)
    normal_response = _get_normal_response(step_input)
    handler_msg = session_state.get("handler_message", "")

    if grade < 3:
        content = (
            f"Desculpe pelo inconveniente. {handler_msg}\n\n"
            f"Aqui está uma resposta melhor:\n{normal_response}"
        )
    else:
        content = (
            f"{handler_msg}\n\n{normal_response}" if handler_msg else normal_response
        )

    return StepOutput(content=content)