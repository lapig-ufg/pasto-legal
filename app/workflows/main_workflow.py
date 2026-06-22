from typing import Any, Dict

from agno.workflow import Workflow, Step, Parallel, Condition, Router
from agno.workflow.types import StepInput, StepOutput

from app.database.agno_db import db
from app.workflows.satisfaction_steps import satisfaction_evaluation_steps
from app.workflows.main_steps import run_steps


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

# --------------------- Greetings ---------------------------------

def greetings_evaluator(step_input: StepInput, session_state: Dict[str, Any]):
    is_greeted = session_state.get("is_greeted", False)

    if is_greeted:
        return True
    else:
        session_state["is_greeted"] = True
        return False


def greetings_executor(step_input: StepInput):
    return StepOutput(content="Olá, seja bem-vindo ao Pato Legal. Como posso te ajudar hoje?")


def steps_selector(step_input: StepInput, session_state: Dict[str, Any]):
    path = session_state.get("path", None)

    if path is None:
        path = 


pasto_legal_workflow = Workflow(
    name="Pasto Legal Workflow",
    db=db,
    steps=[
        Condition(
            name="First Time in Here?",
            evaluator=greetings_evaluator,
            steps=[Step(name="Greetings", executor=greetings_executor)],
            else_steps=[
                Router(
                    name="Main Paths",
                    selector=steps_selector,
                    choices=[
                        main_steps
                    ],
                )
            ]
        )
    ],
)

if __name__=="__main__":
    pasto_legal_workflow.print_response("Olá, tudo bem?")