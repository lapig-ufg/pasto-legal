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


# TODO: implement persistence once PositiveFeedback/NegativeFeedback tables
# are finalized and _mask_pii is available from app.guardrails.pii_gate.
def persist_positive_feedback(
    step_input: StepInput,
    session_state: Dict[str, Any],
) -> StepOutput:
    """Persist a positive interaction to the PositiveFeedback table
    for future fine-tuning. (Stub — persistence logic disabled.)
    """
    # grade = session_state.get("satisfaction_grade", 3)
    # user_msg = step_input.get_input_as_string() or ""
    # normal_response = _get_normal_response(step_input)
    # handler_msg = session_state.get("handler_message", "")
    #
    # PositiveFeedback.metadata.create_all(bind=engine)
    # session = SessionLocal()
    # try:
    #     novo_feedback = PositiveFeedback(
    #         timestamp=datetime.now().isoformat(),
    #         user_message=_mask_pii(user_msg),
    #         assistant_response=_mask_pii(normal_response),
    #         handler_message=_mask_pii(handler_msg),
    #         grade=grade,
    #         context=_mask_pii(normal_response),
    #     )
    #     session.add(novo_feedback)
    #     session.commit()
    #     log_debug("Positive feedback saved by workflow.")
    # except Exception as e:
    #     session.rollback()
    #     log_error(f"Erro ao registrar positive feedback: {e}")
    # finally:
    #     session.close()

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
    # user_msg = step_input.get_input_as_string() or ""
    # normal_response = _get_normal_response(step_input)
    # handler_msg = session_state.get("handler_message", "")
    #
    # NegativeFeedback.metadata.create_all(bind=engine)
    # session = SessionLocal()
    # try:
    #     novo_feedback = NegativeFeedback(
    #         timestamp=datetime.now().isoformat(),
    #         original_question="Original Question",  # TODO: should be the message that caused frustration
    #         reason_frustration=user_msg,
    #         desired_answer=_mask_pii(normal_response),
    #         context=_mask_pii(handler_msg),
    #     )
    #     session.add(novo_feedback)
    #     session.commit()
    #     log_debug("negative feedback saved by workflow.")
    # except Exception as e:
    #     session.rollback()
    #     log_error(f"Erro ao registrar negative feedback: {e}")
    # finally:
    #     session.close()

    return StepOutput(content="Negative Feedback Saved")