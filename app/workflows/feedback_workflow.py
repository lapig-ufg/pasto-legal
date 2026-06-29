from typing import Any, Dict
from datetime import datetime

from agno.run import RunContext
from agno.workflow import Workflow, Step, Steps, Router, Condition, Parallel
from agno.workflow.types import StepInput, StepOutput
from agno.utils.log import log_error, log_debug

from app.agents.feedback_agent import satisfaction_evaluation_agent, remediation_agent
from app.agents.persona_agent import persona_manager_agent
from app.configs.config import config
from app.database.session import engine, SessionLocal
from app.database.models import NegativeFeedback, PositiveFeedback
from app.tools.feedback_tools import _mask_pii
from app.utils.interfaces.user_mood import UserMood, Effectiveness


DEFAULT_SATISFACTION_LEVEL = 3


def save_negative_feedback(
    step_input: StepInput,
    session_state: Dict[str, Any],
    run_context: RunContext = None,
) -> StepOutput:
    """Persist a frustrated interaction to the NegativeFeedback table."""
    #user_msg = step_input.get_input_as_string() or ""
    #normal_response = _get_normal_response(step_input)
    #handler_msg = session_state.get("handler_message", "")
    #
    #NegativeFeedback.metadata.create_all(bind=engine)
    #session = SessionLocal()
    #try:
    #    novo_feedback = NegativeFeedback(
    #        timestamp=datetime.now().isoformat(),
    #        original_question="Original Question", # TODO: Deveria ser a mensagem que gerou a frustração (a mensagem anterior à run atual)
    #        reason_frustration=user_msg, 
    #        desired_answer=_mask_pii(normal_response),
    #        context=_mask_pii(handler_msg),
    #    )
    #    session.add(novo_feedback)
    #    session.commit()
    #    log_debug("negative feedback saved by workflow.")
    #except Exception as e:
    #    session.rollback()
    #    log_error(f"Erro ao registrar negative feedback: {e}")
    #finally:
    #    session.close()

    return StepOutput(content="Negative Feedback Saved")


def save_positive_feedback(
    step_input: StepInput,
    session_state: Dict[str, Any],
    run_context: RunContext = None,
) -> StepOutput:
    """Persist an positive interaction to the PositiveFeedback table for future fine-tuning."""
    #grade = session_state.get("satisfaction_grade", 3)
    #user_msg = step_input.get_input_as_string() or ""
    #normal_response = _get_normal_response(step_input)
    #handler_msg = session_state.get("handler_message", "")
    #
    #PositiveFeedback.metadata.create_all(bind=engine)
    #session = SessionLocal()
    #try:
    #    novo_feedback = PositiveFeedback(
    #        timestamp=datetime.now().isoformat(),
    #        user_message=_mask_pii(user_msg),
    #        assistant_response=_mask_pii(normal_response),
    #        handler_message=_mask_pii(handler_msg),
    #        grade=grade,
    #        context=_mask_pii(normal_response),
    #    )
    #    session.add(novo_feedback)
    #    session.commit()
    #    log_debug("Positive feedback saved by workflow.")
    #except Exception as e:
    #    session.rollback()
    #    log_error(f"Erro ao registrar positive feedback: {e}")
    #finally:
    #    session.close()

    return StepOutput(content="Positive Feedback Saved")

# ---------------------------------------------------------------------------
# Step executors
# ---------------------------------------------------------------------------
def satisfaction_evaluation(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Grade the user's message on a 1-5 scale and store it in session_state."""
    user_msg = step_input.get_input_as_string() or ""
    user_mood = session_state.get("user_mood", None)

    try:
        response = satisfaction_evaluation_agent.run(user_msg, session_state={"user_mood": user_mood})
        if response and response.content:
            effectiveness = response.content
    except Exception as e:
        log_error(f"Satisfaction Evaluation Agent agent failed: {e}")

    if user_mood is None:
        session_state["user_mood"] = {}
        session_state["user_mood"]["satisfaction"] = effectiveness
    else:
        session_state["user_mood"]["remediation"] = effectiveness

    return StepOutput(content=f"The user satisfaction was evaluated as {effectiveness["level"]} ({effectiveness["level_message"]}).")


# ---------------------------------------------------------------------------
# Branching — Agno's Condition is two-way only, so a 3-way branch is built
# with nested Conditions on the grade stored in session_state.
# ---------------------------------------------------------------------------
def satisfaction_level_selector(step_input: StepInput, session_state: Dict[str, Any]):
    user_mood = session_state.get("user_mood", {})
    if not user_mood:
        return ["Neutral"]

    satisfaction_level = user_mood.get("satisfaction", {}).get("level", 3)

    if satisfaction_level == 5:
        return ["Positive Feedback"]
    elif satisfaction_level == 1:
        effectiveness = user_mood.get("remediation", {}).get("effectiveness", {})

        if not effectiveness or effectiveness.get("level", 2) <= 2:
            return ["Negative Feedback"]

    return ["Neutral"]


def negative_satisfaction_evaluator(step_input: StepInput, session_state: Dict[str, Any]):
    user_mood = session_state.get("user_mood", {})
    if not user_mood:
        return False
    
    satisfaction = user_mood.get("satisfaction", {})
    if not satisfaction:
        return False
    
    return satisfaction.get("level") <= 2


def clear_user_mood(step_input: StepInput, session_state: Dict[str, Any]):
    session_state["user_mood"] = None

# ---------------------------------------------------------------------------
# Evaluation branch — grade the message, then branch on the grade.
# ---------------------------------------------------------------------------
feedback_workflow = Workflow(
    name="Feedback Workflow",
    steps=[
        Step(
            name="Satisfaction Evaluation",
            executor=satisfaction_evaluation
        ),
        Parallel(
            Router(
                name="Satisfaction Level Router",
                selector=satisfaction_level_selector,
                choices=[
                    Steps(
                        name="Positive Feedback",
                        steps=[
                            Step(
                                name="Save Positive Feedback",
                                executor=save_positive_feedback
                            ),
                            Step(
                                name="Clear User Mood",
                                executor=clear_user_mood
                            )
                        ]
                    ),
                    Steps(
                        name="Negative Feedback",
                        steps=[
                            Step(
                                name="Save Negative Feedback",
                                executor=save_negative_feedback
                            ),
                            Step(
                                name="Clear User Mood",
                                executor=clear_user_mood
                            )
                        ]
                    ),
                    Step(
                        name="Neutral",
                        executor=lambda step_input: None
                    )
                ]
            ),
            Step(
                name="Managing Persona",
                agent=persona_manager_agent
            ),
            name="Evaluation Parallel"
        )
    ]
)


merge_output_step = Condition(
    name="Merge Output Step",
    evaluator=negative_satisfaction_evaluator,
    steps=[
        Step(
            name="Merge Remediation",
            agent=remediation_agent
        )
    ],
    else_steps=[
        Step(
            name="Foward",
            executor=lambda step_input: step_input.get_last_step_content()
        )
    ]
)