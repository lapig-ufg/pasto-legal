from typing import Any, Dict
from datetime import datetime

from pydantic import BaseModel

from agno.run import RunContext
from agno.agent import Agent
from agno.workflow import Workflow, Steps, Step, Condition, Parallel
from agno.workflow.types import StepInput, StepOutput
from agno.utils.log import log_error, log_debug

from app.configs.config import config
from app.database.agno_db import db
from app.database.session import SessionLocal, engine
from app.database.models import FrustrationFeedback, PositiveFeedback
from app.agents import pasto_legal_team
from app.tools.feedback_tools import _mask_pii


# Check user phone number authorization.
def phone_number_check(run_context: RunContext):
    session_state = run_context.session_state

    user_id = session_state.get('user_id', None)

    if user_id is None:
        return False

    user_phone_number = user_id.replace("wa:", "")

    try:
        with open(f'phone_numbers.in', 'r', encoding='utf-8') as file:

            for line in file:
                if line.strip() == user_phone_number.strip():
                    return

    except FileNotFoundError:
        log_error("FileNotFoundError: phone_numbers.in.")
    except Exception as e:
        log_error(f"Exception: {e}.")


# ---------------------------------------------------------------------------
# Satisfaction grading
# ---------------------------------------------------------------------------
# The user's message is graded on a 1-5 scale:
#   1 = completely frustrated, 3 = neutral, 5 = amazed.
# The grade drives the branching below and the merge step at the end.
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

neutral_handler_agent = Agent(
    name="Neutral Handler",
    model=config.model,
    instructions=(
        "O usuário está neutro em relação à resposta anterior. Escreva uma mensagem curta "
        "em português, agradecendo o retorno e oferecendo ajuda adicional. Não use bullet points."
    ),
    use_instruction_tags=False,
    debug_mode=config.DEBUG_MODE,
)

amazed_handler_agent = Agent(
    name="Amazed Handler",
    model=config.model,
    instructions=(
        "O usuário está encantado com a resposta anterior. Escreva uma mensagem curta e "
        "entusiasmada em português, celebrando o bom resultado. Não use bullet points."
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
def grade_satisfaction(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
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
    session_state["satisfaction_grade"] = grade
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


# ---------------------------------------------------------------------------
# Branching — Agno's Condition is two-way only, so a 3-way branch is built
# with nested Conditions on the grade stored in session_state.
# ---------------------------------------------------------------------------
def is_frustrated(step_input: StepInput, session_state: Dict[str, Any]) -> bool:
    return session_state.get("satisfaction_grade", 3) < 3


def is_amazed(step_input: StepInput, session_state: Dict[str, Any]) -> bool:
    return session_state.get("satisfaction_grade", 3) > 3


branch_on_grade = Condition(
    name="branch_on_grade",
    evaluator=is_frustrated,
    steps=[
        Step(name="handle_frustration", executor=handle_frustration),
        Step(name="save_frustration", executor=save_frustration),
    ],
    else_steps=[
        Condition(
            name="amazed_or_neutral",
            evaluator=is_amazed,
            steps=[
                Step(name="amazed_handler", executor=handle_amazed),
                Step(name="save_amazed", executor=save_amazed),
            ],
            else_steps=[
                Step(name="neutral_handler", executor=handle_neutral),
            ],
        )
    ],
)

# ---------------------------------------------------------------------------
# Workflow assembly
# ---------------------------------------------------------------------------
pasto_legal_workflow = Workflow(
    name="Pasto Legal Workflow",
    db=db,
    steps=[
        Parallel(
            Steps(
                name="evaluation_branch",
                steps=[
                    Step(name="grade_satisfaction", executor=grade_satisfaction),
                    branch_on_grade,
                ],
            ),
            Step(name="normal_response", team=pasto_legal_team),
            name="grade_and_respond"
        ),
        Step(name="merge_response", executor=merge_response),
    ],
)