from typing import Any, Dict

from agno.workflow import Workflow, Step, Parallel, Condition, Router
from agno.workflow.types import StepInput, StepOutput

from app.agents import (
    pasto_legal_team,
    question_answer_agent,
    property_manager_agent,
    property_analyst_agent,
)
from app.database.agno_db import db
from app.workflows.run_workflow import run_workflow


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
    return session_state.get("path", "Run Workflow")


pasto_legal_workflow = Workflow(
    name="Pasto Legal Workflow",
    steps=[
        Condition(
            name="First Time in Here?",
            evaluator=greetings_evaluator,
            steps=[
                Step(
                    name="Greetings",
                    executor=greetings_executor
                )
            ],
            else_steps=[
                Router(
                    name="Main Paths",
                    selector=steps_selector,
                    choices=[
                        Step(
                            name="Run Workflow",
                            workflow=run_workflow
                        ),
                        Step(
                            name="Registration Agent",
                            agent=property_manager_agent
                        )
                    ],
                )
            ]
        )
    ],
    db=db,
)


if __name__=="__main__":
    response = pasto_legal_workflow.run("Olá, tudo bem?")
    print(response.content)