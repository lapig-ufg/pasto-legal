"""Satisfaction grading and the grade-driven branch (the "evaluation_branch").

The user's message is graded on a 1-5 scale (1 = completely frustrated,
3 = neutral, 5 = amazed). The grade drives a 3-way branch (nested
Conditions, since Agno's Condition is two-way only) into tailored handler
messages and DB saves. This module exports the assembled `evaluation_branch`
Steps used by the main workflow.
"""
from typing import Any, Dict

from pydantic import BaseModel

from agno.agent import Agent
from agno.workflow import Step, Condition, Steps
from agno.workflow.types import StepInput, StepOutput
from agno.utils.log import log_error, log_debug

from app.configs.config import config
from app.workflows.feedback import save_frustration, save_amazed


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
# Evaluation branch — grade the message, then branch on the grade.
# ---------------------------------------------------------------------------
evaluation_branch = Steps(
    name="evaluation_branch",
    steps=[
        Step(name="grade_satisfaction", executor=grade_satisfaction),
        branch_on_grade,
    ],
)