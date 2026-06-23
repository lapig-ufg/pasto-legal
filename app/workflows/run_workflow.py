from typing import Any, Dict

from pydantic import BaseModel

from agno.agent import Agent
from agno.workflow import Workflow, Step, Parallel
from agno.workflow.types import StepInput, StepOutput
from agno.utils.log import log_error

from app.agents import (
    pasto_legal_team,
    question_answer_agent,
    property_manager_agent,
    property_analyst_agent,
)
from app.configs.config import config
from app.workflows.steps_names import MainSteps
from app.workflows.feedback_workflow import feedback_workflow, remediation_step


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
run_workflow = Workflow(
    steps=[
        Parallel(
            feedback_workflow,
            Step(name=MainSteps.MAIN_PARALLEL_STEP_1.value, team=pasto_legal_team),
            name=MainSteps.MAIN_PARALLEL.value,
        ),
        remediation_step
    ]
)