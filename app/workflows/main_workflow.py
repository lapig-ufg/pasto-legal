"""Main workflow composition for the Pasto Legal multi-agent system.

Defines the root workflow (`pasto_legal_workflow`) that orchestrates greeting
detection, agent routing, feedback evaluation, and response merging.

External interface:
    pasto_legal_workflow  -- the Workflow instance imported by app.main,
                            app.interfaces.streamlit.streamlit_webapp, and
                            app.utils.debug_panel.
"""

# --- Imports ---

from typing import Any, Dict

from agno.utils.log import log_debug
from agno.workflow import Condition, Parallel, Router, Step, Workflow
from agno.workflow.types import StepInput, StepOutput

from app.agents import (
    analyst_agent,
    manager_agent,
    question_answer_agent,
    router_agent,
    small_talk_agent,
)
from app.database.agno_db import db
from app.utils.interfaces.workflow_state import WorkflowRouteEnum, WorkflowState
from app.workflows.feedback_workflow import feedback_workflow, merge_output_step
from app.agents.welcoming_agent import welcoming_agent
from app.database.session import SessionLocal
from app.database.models import UserTermsAcceptance


# --- Step Executors ---

def needs_onboarding(step_input: StepInput, session_state: Dict[str, Any]) -> bool:
    """
    Determines whether the user needs to go through onboarding. 
    Returns True if the terms have NOT yet been accepted.
    """

    if session_state.get("workflow_state") is None:
        session_state["workflow_state"] = WorkflowState().model_dump()

    if session_state.get("terms_accepted"):
        return False
        
    user_id = session_state.get("user_id") 
    if not user_id:
        return True 

    db = SessionLocal()
    try:
        record = db.query(UserTermsAcceptance).filter(
            UserTermsAcceptance.user_id == user_id, 
            UserTermsAcceptance.accepted == True
        ).first()
        
        if record:
            session_state["terms_accepted"] = True
            return False
            
        return True
    finally:
        db.close()

def route_selector(step_input: StepInput, session_state: Dict[str, Any]) -> str:
    """Selector for the Intent Router. Runs the Router Agent to classify
    the user's message and returns the matching route enum value.

    If a non-AUTO route is already set in WorkflowState, returns it directly
    (manual override). Falls back to 'default' if the agent fails or the
    session state does not contain a valid WorkflowState.
    """
    raw_state = session_state.get("workflow_state")
    if raw_state is None:
        log_debug("route_selector: no workflow_state in session, defaulting to 'default'")
        return "default"

    try:
        workflow_state = WorkflowState.model_validate(raw_state)
    except Exception as e:
        log_debug(f"route_selector: invalid workflow_state: {e}, defaulting to 'default'")
        return "default"

    if workflow_state.route != WorkflowRouteEnum.AUTO:
        return workflow_state.route.value

    try:
        user_msg = step_input.get_input_as_string()
        history_data = step_input.get_workflow_history(num_runs=1)
        
        final_message=""
        if history_data:
            last_user_msg, last_system_response = history_data[0]
            final_message+="### Talk History ###"
            final_message+=f"User: {last_user_msg}"
            final_message+=f"System: {last_system_response}"
        final_message=f"User: {user_msg}"

        response = router_agent.run(final_message)
        route_data = response.content

        if route_data and hasattr(route_data, "route"):
            return route_data.route

        if isinstance(route_data, dict) and "route" in route_data:
            return route_data["route"]
        
        if isinstance(route_data, str) and len(route_data.split(" ")) == 1:
            return route_data

    except Exception as e:
        log_debug(f"route_selector: agent failed: {e}")

    return "default"


def _extract_last_step_output(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Extract the deepest content from the last step in previous_step_outputs.

    This is a utility executor that extracts the final meaningful output
    from the workflow's preceding steps, used to normalize the workflow's
    output after branching (Condition/Router/Parallel).

    Falls back to an empty StepOutput if no previous outputs are available.
    """
    if not step_input.previous_step_outputs:
        log_debug("_extract_last_step_output: no previous_step_outputs available")
        return StepOutput(content="")

    last_output = list(step_input.previous_step_outputs.values())[-1]

    if not last_output.steps:
        return last_output

    return last_output.steps[-1]


# --- Workflow Definition ---

pasto_legal_workflow = Workflow(
    name="Pasto Legal Workflow",
    db=db,
    add_workflow_history_to_steps=True,
    num_history_runs=1,
    steps=[
        Condition(
            name="Onboarding Check", 
            evaluator=needs_onboarding, 
            steps=[
                Step(
                    name="Welcoming Agent",
                    agent=welcoming_agent, 
                ),
            ],
            else_steps=[
                Parallel(
                    feedback_workflow,
                    Router(
                        name="Intent Router",
                        selector=route_selector,
                        choices=[
                            Step(
                                name="default",
                                executor=lambda x: None,
                            ),
                            Step(
                                name=WorkflowRouteEnum.ANALYST.value,
                                agent=analyst_agent,
                            ),
                            Step(
                                name=WorkflowRouteEnum.MANAGER.value,
                                agent=manager_agent,
                            ),
                            Step(
                                name=WorkflowRouteEnum.QUESTION_ANSWER.value,
                                agent=question_answer_agent,
                            ),
                            Step(
                                name=WorkflowRouteEnum.SMALL_TALK.value,
                                agent=small_talk_agent,
                            ),
                        ],
                    ),
                    name="Feedback and Routing",
                ),
                merge_output_step,
                Step(
                    name="Extract Last Output",
                    executor=_extract_last_step_output,
                ),
            ],
        ),
        Step(
            name="Extract Last Output",
            executor=_extract_last_step_output,
        ),
    ],
)