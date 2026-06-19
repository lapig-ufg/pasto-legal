from typing import Any, Dict
from datetime import datetime

from pydantic import BaseModel

from agno.agent import Agent
from agno.run import RunContext
from agno.workflow import Step, Steps, Router
from agno.workflow.types import StepInput, StepOutput
from agno.utils.log import log_error, log_debug

from app.configs.config import config
from app.database.session import engine, SessionLocal
from app.database.models import FrustrationFeedback, PositiveFeedback
from app.tools.feedback_tools import _mask_pii


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


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------
class SatisfactionGrade(BaseModel):
    grade: int


grader_agent = Agent(
    name="Satisfaction Grader",
    model=config.model,
    output_schema=SatisfactionGrade,
    instructions=(
        "Avalie a satisfação do usuário de acordo com a mensagem enviada. "
        "1 = completamente frustrado, 3 = neutro, 5 = encantado. "
        'Responda apenas com o JSON {"grade": int}.'
    ),
    use_instruction_tags=False,
    debug_mode=config.DEBUG_MODE,
)


# ---------------------------------------------------------------------------
# Branch handlers — each crafts a tailored message stored in session_state
# for the merge step to consume.
# ---------------------------------------------------------------------------
frustration_handler_agent = Agent(
    name="Frustration Handler",
    model=config.model,
    instructions=(
        "O usuário está frustrado com a resposta anterior. Escreva uma mensagem curta, "
        "empática e em português, reconhecendo o erro e indicando que uma resposta melhor "
        "virá a seguir. Não use bullet points."
    ),
    use_instruction_tags=False,
    debug_mode=config.DEBUG_MODE,
)


def _run_handler(agent: Agent, user_msg: str) -> str:
    """Run a handler agent and return its content (empty string on failure)."""
    try:
        response = agent.run(user_msg)
        return response.content if response and response.content else ""
    except Exception as e:
        log_error(f"Handler agent failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Step executors
# ---------------------------------------------------------------------------
def satisfaction_evaluation(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Grade the user's message on a 1-5 scale and store it in session_state."""
    user_msg = step_input.get_input_as_string() or ""

    grade = 3  # neutral fallback
    try:
        response = grader_agent.run(user_msg)
        if response and response.content:
            grade = int(getattr(response.content, "grade", 3))
    except Exception as e:
        log_error(f"Grader agent failed: {e}")

    grade = max(1, min(5, grade))
    session_state["satisfaction_level"] = grade
    log_debug(f"Satisfaction grade: {grade}")
    return StepOutput(content=grade)


def handle_frustration(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    user_msg = step_input.get_input_as_string() or ""
    session_state["handler_message"] = _run_handler(frustration_handler_agent, user_msg)
    return StepOutput(content=session_state["handler_message"])


def handle_neutral(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    user_msg = step_input.get_input_as_string() or ""
    session_state["handler_message"] = _run_handler(neutral_handler_agent, user_msg)
    return StepOutput(content=session_state["handler_message"])


def handle_amazed(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    user_msg = step_input.get_input_as_string() or ""
    session_state["handler_message"] = _run_handler(amazed_handler_agent, user_msg)
    return StepOutput(content=session_state["handler_message"])


# ---------------------------------------------------------------------------
# Branching — Agno's Condition is two-way only, so a 3-way branch is built
# with nested Conditions on the grade stored in session_state.
# ---------------------------------------------------------------------------
def satisfaction_selector(step_input: StepInput, session_state: Dict[str, Any]):
    satisfaction_level = session_state.get("satisfaction_level", 3)

    if satisfaction_level == 3:
        return ["neutral_handler"]
    elif satisfaction_level > 3:
        return ["amazed_steps"]
    elif satisfaction_level < 3:
        return ["frustration_steps"]


branch_satisfaction_level = Router(
    name="branch_satisfaction_level",
    selector=satisfaction_selector,
    choices=[
        Steps(
            name="frustration_steps",
            steps=[
                Step(name="handle_frustration", executor=handle_frustration),
                Step(name="save_frustration", executor=save_frustration)
            ]
        ),
        Steps(
            name="amazed_steps",
            steps=[
                Step(name="amazed_handler", executor=handle_amazed),
                Step(name="save_amazed", executor=save_amazed),
            ]
        ),
        Step(name="neutral_handler", executor=handle_neutral)
    ],
    allow_multiple_selections=False
)


# ---------------------------------------------------------------------------
# Evaluation branch — grade the message, then branch on the grade.
# ---------------------------------------------------------------------------
satisfaction_evaluation_steps = Steps(
    name="satisfaction_evaluation_branch",
    steps=[
        Step(name="satisfaction_evaluation", executor=satisfaction_evaluation),
        branch_satisfaction_level,
    ],
)