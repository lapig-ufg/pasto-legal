"""Main workflow composition for the Pasto Legal multi-agent system.

Defines the root workflow (`pasto_legal_workflow`) that orchestrates greeting
detection, agent routing, feedback evaluation, and response merging. This is
a thin composition file; all executor logic lives in ``app.steps`` and shared
workflow infrastructure in ``app.core``.

External interface:
    pasto_legal_workflow  -- the Workflow instance imported by app.main,
                             app.interfaces.streamlit.streamlit_webapp, and
                             app.interfaces.streamlit.debug_panel.
"""
from typing import Any, Dict

from agno.utils.log import log_debug
from agno.workflow import Condition, Parallel, Router, Step, Steps
from agno.workflow.types import StepInput, StepOutput

from app.agents.router_agent import router_agent
from app.agents.welcoming_agent import welcoming_agent
from app.configs.config import config
from app.models.persist_on_success_workflow import PersistOnSuccessWorkflow
from app.schemas.workflow_state import WorkflowState, RouteEnum
from app.core.step_factory import _agent_executor_factory
from app.database.agno_db import db
from app.database.models import UserTermsAcceptance
from app.database.session import SessionLocal
from app.steps.routing import (
    analyst_step,
    manager_step,
    question_answer_step,
    small_talk_step
)
from app.steps.feedback.remediation import remediation_check_step
from app.steps.output_step import output_step
from app.steps.guardrails_step import guardrails_step
from app.steps.input_step import input_step
from app.steps.summarization_step import summarization_step
from app.workflows.feedback_workflow import feedback_workflow
from app.steps.scope_step import scope_step


def _route_selector(step_input: StepInput, session_state: Dict[str, Any]) -> str:
    """Selector for the Intent Router. Runs the Router Agent to classify
    the user's message and returns the matching route enum value.
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

    if workflow_state.route != RouteEnum.AUTO:
        return workflow_state.route.value

    try:
        user_msg = step_input.get_input_as_string() or ""
        history_data = step_input.get_workflow_history(num_runs=1)

        final_message = ""
        if history_data:
            last_user_msg, last_system_response = history_data[0]
            final_message += "### Talk History ###\n"
            final_message += f"User: {last_user_msg}\n"
            final_message += f"System: {last_system_response}\n"
        final_message += f"User: {user_msg}"

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


def _needs_onboarding(step_input: StepInput, session_state: Dict[str, Any]) -> bool:
    """Return True if the user needs to go through onboarding.

    Returns True if the terms have NOT yet been accepted. Lazily initializes
    the ``workflow_state`` slot in ``session_state`` when missing.
    """
    if session_state.get("workflow_state") is None:
        session_state["workflow_state"] = WorkflowState().model_dump()

    if session_state.get("terms_accepted"):
        return False

    user_id = session_state.get("user_id")
    if not user_id:
        return True

    db_session = SessionLocal()
    try:
        record = db_session.query(UserTermsAcceptance).filter(
            UserTermsAcceptance.user_id == user_id,
            UserTermsAcceptance.accepted == True,
        ).first()

        if record:
            session_state["terms_accepted"] = True
            return False

        return True
    finally:
        db_session.close()


pasto_legal_workflow = PersistOnSuccessWorkflow(
    name="Pasto Legal Workflow",
    db=db,
    debug_mode=config.DEBUG_MODE,
    add_workflow_history_to_steps=True,
    num_history_runs=1,
    steps=[
        input_step,
        guardrails_step,
        scope_step, 
        Condition(
            name="Onboarding Check",
            evaluator=_needs_onboarding,
            steps=[
                Step(
                    name="Welcoming Agent",
                    executor=_agent_executor_factory(welcoming_agent, include_summary=False),
                ),
            ],
            else_steps=[
                Parallel(
                    summarization_step,
                    feedback_workflow,
                    Router(
                        name="Intent Router",
                        selector=_route_selector,
                        choices=[
                            Step(
                                name="default",
                                executor=lambda step_input: None,
                            ),
                            analyst_step,
                            manager_step,
                            question_answer_step,
                            small_talk_step
                        ],
                    ),
                    name="Feedback and Routing",
                ),
                remediation_check_step,
            ],
        ),
        output_step
    ],
)