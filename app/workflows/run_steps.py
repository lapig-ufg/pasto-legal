from typing import Any, Dict, List

from pydantic import BaseModel

from agno.agent import Agent
from agno.workflow import Step, Condition, Steps, Loop, OnReject
from agno.workflow.types import StepInput, StepOutput, HumanReview, OnTimeout
from agno.utils.log import log_error

from app.configs.config import config
from app.agents import (
    pasto_legal_team,
    question_answer_agent,
    property_manager_agent,
    property_analyst_agent,
)


# ---------------------------------------------------------------------------
# Question classification (system vs technical/EMBRAPA)
# ---------------------------------------------------------------------------
class QuestionType(BaseModel):
    is_system_question: bool


question_classifier_agent = Agent(
    name="Question Classifier",
    model=config.model,
    output_schema=QuestionType,
    instructions=(
        "Classifique a pergunta do usuário. is_system_question=true se for sobre o uso da "
        "plataforma, guias, FAQ, navegação ou terminologia. is_system_question=false se for "
        "sobre pastagem, propriedade, gado, agronomia ou conhecimento técnico da EMBRAPA. "
        'Responda apenas com o JSON {"is_system_question": bool}.'
    ),
    use_instruction_tags=False,
    debug_mode=config.DEBUG_MODE,
)


# ---------------------------------------------------------------------------
# Evaluators
# ---------------------------------------------------------------------------
def is_system_question(step_input: StepInput, session_state: Dict[str, Any]) -> bool:
    """Classify the user's message: system/guide vs technical (EMBRAPA)."""
    user_msg = step_input.get_input_as_string() or ""
    try:
        response = question_classifier_agent.run(user_msg)
        if response and response.content:
            return bool(getattr(response.content, "is_system_question", False))
    except Exception as e:
        log_error(f"Question classifier failed: {e}")
    return False  # default: treat as technical -> property flow


def has_registered_property(step_input: StepInput, session_state: Dict[str, Any]) -> bool:
    """True if at least one property is registered in session_state."""
    return bool(session_state.get("registered_properties", []))


def property_name_set(step_input: StepInput, session_state: Dict[str, Any]) -> bool:
    """True if set_property_name has run successfully this registration cycle."""
    return bool(session_state.get("property_name_set", False))


# ---------------------------------------------------------------------------
# Registration loop helpers
# ---------------------------------------------------------------------------
def reset_registration_flag(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Clear a stale flag from a previous run so the Loop starts fresh."""
    session_state["property_name_set"] = False
    return StepOutput(content="")


def check_registration_done(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Surface the flag into a StepOutput so the Loop's end_condition can see it.

    The Loop's end_condition only receives List[StepOutput] (no session_state),
    so this step reads the flag and returns "DONE" when set. When not done it
    forwards the agent's previous content so the conversation continues across
    iterations (forward_iteration_output=True).
    """
    if session_state.get("property_name_set", False):
        return StepOutput(content="DONE")
    return StepOutput(content=step_input.get_last_step_content() or "")


def _registration_end_condition(iteration_results: List[StepOutput]) -> bool:
    """Exit the registration loop once set_property_name has run."""
    return any(getattr(so, "content", "") == "DONE" for so in iteration_results)


def property_canceled(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Fallback when the registration loop never completes."""
    return StepOutput(
        content=(
            "Não foi possível concluir o cadastro da propriedade após várias tentativas. "
            "O registro foi cancelado. Tente novamente mais tarde."
        )
    )


# ---------------------------------------------------------------------------
# Normal-response branch assembly
# ---------------------------------------------------------------------------
run_steps = Condition(
    name="run_steps",
    evaluator=is_system_question,
    steps=[Step(name="answer_system", agent=question_answer_agent)],
    else_steps=[
        Condition(
            name="check_registered_property",
            evaluator=has_registered_property,
            steps=[Step(name="team_response", team=pasto_legal_team)],
            else_steps=[
                Steps(
                    name="register_and_analyze",
                    steps=[
                        Step(name="reset_registration_flag", executor=reset_registration_flag),
                        Loop(
                            name="property_registration_loop",
                            steps=[
                                Step(name="property_manager", agent=property_manager_agent),
                                Step(name="check_registration_done", executor=check_registration_done),
                            ],
                            max_iterations=5,
                            forward_iteration_output=True,
                            end_condition=_registration_end_condition,
                        ),
                        Condition(
                            name="registered_or_canceled",
                            evaluator=property_name_set,
                            steps=[
                                Step(
                                    name="preliminary_analysis",
                                    agent=property_analyst_agent,
                                    human_review=HumanReview(
                                        requires_output_review=True,
                                        output_review_message="Revise a análise preliminar da propriedade antes de enviar.",
                                        on_reject=OnReject.retry,
                                        max_retries=3,
                                        timeout=300,
                                        on_timeout=OnTimeout.approve,
                                    ),
                                ),
                            ],
                            else_steps=[Step(name="property_canceled", executor=property_canceled)],
                        ),
                    ],
                ),
            ],
        ),
    ],
)