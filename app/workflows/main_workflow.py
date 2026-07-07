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


# --- Step Executors ---


def is_first_interaction(step_input: StepInput, session_state: Dict[str, Any]) -> bool:
    """Condition evaluator that returns True when this is the user's first
    interaction (no workflow_state in session yet).

    Also initializes session_state['workflow_state'] with a fresh WorkflowState
    so that subsequent turns have a valid routing state.
    """
    workflow_state_dict = session_state.get("workflow_state", None)

    if workflow_state_dict is None:
        session_state["workflow_state"] = WorkflowState().model_dump()
        return True

    return False


def welcome_message_executor(step_input: StepInput) -> StepOutput:
    """Return a static welcome message for first-time users."""
    return StepOutput(content="Olá, seja bem-vindo ao Pato Legal. Como posso te ajudar hoje?")


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
        if not user_msg:
            log_debug("route_selector: empty user message, defaulting to 'default'")
            return "default"

        response = router_agent.run(user_msg)
        route_data = response.content

        if route_data and hasattr(route_data, "route"):
            return route_data.route

        if isinstance(route_data, dict) and "route" in route_data:
            return route_data["route"]

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
    steps=[
        Condition(
            name="Is First Interaction",
            evaluator=is_first_interaction,
            steps=[
                Step(
                    name="Welcome Message",
                    executor=welcome_message_executor,
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