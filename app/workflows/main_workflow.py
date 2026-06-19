from typing import Any, Dict


from agno.workflow import Workflow, Step, Parallel
from agno.workflow.types import StepInput, StepOutput

from app.database.agno_db import db
from app.workflows.satisfaction_evaluation_steps import satisfaction_evaluation_steps
from app.workflows.run_steps import run_steps


def _get_run_response(step_input: StepInput) -> str:
    """Pull the normal agent execution output from the parallel branch."""
    content = step_input.get_step_content("run_steps")
    if isinstance(content, dict):
        # Parallel aggregates as {step_name: content}; grab the value if so.
        content = next(iter(content.values())) if content else ""
    return content or ""


def _merge_response(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Merge the evaluation branch with the normal agent response.

    If the user was frustrated (grade < 3), prepend an apology and offer a
    better response. Otherwise, proceed with the normal agent response.
    """
    satisfaction_level = session_state.get("satisfaction_level", 3)
    run_steps_response = _get_run_response(step_input)
    handler_msg = session_state.get("handler_message", "")

    if satisfaction_level < 3:
        content = (
            f"{handler_msg}\n\n"
            f"{run_steps_response}\n\n"
            "Poderia me dizer se essa resposta foi melhor?"
        )
    else:
        content = run_steps_response

    return StepOutput(content=content)


pasto_legal_workflow = Workflow(
    name="Pasto Legal Workflow",
    db=db,
    steps=[
        Parallel(
            satisfaction_evaluation_steps,
            run_steps,
            name="grade_and_respond",
        ),
        Step(name="merge_response", executor=_merge_response),
    ],
)

if __file__=="__main__":
    Workflow.print_response("Olá, tudo bem?")