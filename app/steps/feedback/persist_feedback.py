"""Feedback persistence steps (TODO stubs).

Persist positive / negative interactions to the database for future
fine-tuning and frustration analysis. The persistence logic is currently
commented out pending the finalization of the PositiveFeedback /
NegativeFeedback tables and PII masking helpers.

These stubs are wired into the feedback workflow so the branches exist; once
the tables are ready, uncomment the bodies and remove the TODO markers.

External interface:
    persist_positive_feedback -- StepExecutor consumed by feedback_workflow.
    persist_negative_feedback -- StepExecutor consumed by feedback_workflow.
"""

from typing import Any, Dict

from agno.workflow.types import StepInput, StepOutput
from datetime import datetime
from agno.utils.log import log_debug, log_error
from app.database.session import SessionLocal, engine
from app.database.models import PositiveFeedback, NegativeFeedback
from app.services.fine_tuning_service import build_sft_dataset_row, build_dpo_dataset_row

# TODO: implement persistence once PositiveFeedback/NegativeFeedback tables
# are finalized and _mask_pii is available from app.guardrails.pii_gate.
def persist_positive_feedback(
    step_input: StepInput,
    session_state: Dict[str, Any],
) -> StepOutput:
    """Persist a positive interaction to the PositiveFeedback table
    for future fine-tuning. (Stub — persistence logic disabled.)
    """

    grade = session_state.get("satisfaction_grade", 5)
    user_msg = step_input.get_input_as_string() or ""
    
    session_id = getattr(step_input.workflow_session, "session_id", "unknown") if hasattr(step_input, "workflow_session") else "unknown"
    recent_runs = session_state.get("recent_agent_runs", [])
    
    context_data = {}
    if recent_runs:
        try:
            context_data = build_sft_dataset_row(
                recent_runs=recent_runs,
                session_id=session_id,
                agent_id="single_agent",
                feedback_score=float(grade)
            )
        except Exception as e:
            log_error(f"Erro ao construir linha SFT: {e}")

    PositiveFeedback.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        novo_feedback = PositiveFeedback(
            timestamp=datetime.now().isoformat(),
            user_message=user_msg,
            assistant_response="",
            handler_message="",
            grade=grade,
            context=context_data,
        )
        session.add(novo_feedback)
        session.commit()
        log_debug("Positive feedback saved by workflow.")
        session_state.pop("original_prompt", None)
        session_state.pop("rejected_response", None)
        session_state.pop("chosen_response", None)
        session_state.pop("user_mood", None)
    except Exception as e:
        session.rollback()
        log_error(f"Erro ao registrar positive feedback: {e}")
    finally:
        session.close()


    return StepOutput(content="Positive Feedback Saved")


# TODO: implement persistence once PositiveFeedback/NegativeFeedback tables
# are finalized and _mask_pii is available from app.guardrails.pii_gate.
def persist_negative_feedback(
    step_input: StepInput,
    session_state: Dict[str, Any],
) -> StepOutput:
    """Persist a frustrated interaction to the NegativeFeedback table.
    (Stub — persistence logic disabled.)
    """
    user_msg = step_input.get_input_as_string() or ""
    
    prompt = session_state.get("original_prompt", "")
    rejected = session_state.get("rejected_response", "")
    chosen = session_state.get("chosen_response", "")
    
    context_data = {}
    if prompt and rejected and chosen:
        context_data = build_dpo_dataset_row(
            prompt=prompt,
            rejected=rejected,
            chosen=chosen
        )
    
    NegativeFeedback.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        novo_feedback = NegativeFeedback(
            timestamp=datetime.now().isoformat(),
            original_question=prompt,
            reason_frustration=user_msg,
            desired_answer=chosen,
            context=context_data,
        )
        session.add(novo_feedback)
        session.commit()
        log_debug("Negative feedback saved by workflow.")
        session_state.pop("user_mood", None)
        session_state.pop("original_prompt", None)
        session_state.pop("rejected_response", None)
        session_state.pop("chosen_response", None)
    except Exception as e:
        session.rollback()
        log_error(f"Erro ao registrar negative feedback: {e}")
    finally:
        session.close()


    return StepOutput(content="Negative Feedback Saved")