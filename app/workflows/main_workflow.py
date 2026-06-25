import re
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

#====================================
#
#====================================
def evaluator(step_input: StepInput, session_state: Dict[str, Any]) -> bool:
    is_register_path = session_state.get("workflow_path", {}).get("register_path", False)
    if is_register_path:
        return True

    user_msg = step_input.get_input_as_string()
    if not user_msg:
        return False

    sicar_pattern = r"\b([A-Z]{2})-?(\d{7})-([A-Z0-9]{4})\.?([a-z0-9]{4})\.?([a-z0-9]{4})\.?([a-z0-9]{4})\.?([a-z0-9]{4})\.?([a-z0-9]{4})\.?([a-z0-9]{4})\.?([a-z0-9]{4})\b"
    has_sicar = re.search(sicar_pattern, user_msg, flags=re.IGNORECASE)

    decimal_coords_pattern = r"[-+]?\d{1,3}\.\d+.*\s*[-+]?\d{1,3}\.\d+"
    has_decimal_coords = re.search(decimal_coords_pattern, user_msg)
    
    dms_coords_pattern = r"\d{1,3}°\s*\d{1,2}'\s*\d{1,2}(\.\d+)?\"?\s*[NnSsEeWwOo]"
    has_dms_coords = re.search(dms_coords_pattern, user_msg)
    
    google_maps_pattern = r"(https?://)?(www\.)?(google\.com/maps|maps\.app\.goo\.gl|maps\.google\.com)"
    has_maps = re.search(google_maps_pattern, user_msg, flags=re.IGNORECASE)

    if has_sicar or has_decimal_coords or has_dms_coords or has_maps:
        workflow_path = session_state.get("workflow_path", {})
        workflow_path["register_path"] = True
        session_state["workflow_path"] = workflow_path
        
        return True
    else:
        return False


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
                Condition(
                    name="Run Or Registry?",
                    evaluator=evaluator,
                    steps=[
                        Step(
                            name="Registration Agent",
                            agent=property_manager_agent
                        )
                    ],
                    else_steps=[
                        Step(
                            name="Run Workflow",
                            workflow=run_workflow
                        )
                    ],
                )
            ]
        )
    ],
    db=db
)