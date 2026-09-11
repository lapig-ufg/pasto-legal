"""Main workflow composition for the Pasto Legal system.

Defines the root workflow (`pasto_legal_workflow`) that orchestrates onboarding
(welcoming agent), the single Pasto Legal agent, the parallel feedback/
summarization pipelines, and response merging. Intent routing has been removed:
the single agent handles registration, analysis and Q&A internally, branching
purely on `registration_state`.

External interface:
    pasto_legal_workflow  -- the Workflow instance imported by app.main,
                             app.interfaces.streamlit.streamlit_webapp, and
                             app.interfaces.streamlit.debug_panel.
"""
from typing import Any

from agno.workflow import Condition, Parallel, Step
from agno.workflow.types import StepInput

from app.agents.single_agent import single_agent
from app.agents.welcoming_agent import welcoming_agent
from app.configs.config import config
from app.core.step_factory import _agent_executor_factory
from app.database.agno_db import db
from app.database.models import UserTermsAcceptance
from app.database.session import SessionLocal
from app.models.persist_on_success_workflow import PersistOnSuccessWorkflow
from app.schemas.workflow_state import WorkflowState
from app.steps.feedback.remediation import remediation_check_step, INTENT_ROUTER_STEP_NAME
from app.steps.guardrails_step import guardrails_step
from app.steps.input_step import input_step
from app.steps.output_step import output_step
from app.steps.summarization_step import summarization_step
from app.workflows.feedback_workflow import feedback_workflow


def _needs_onboarding(step_input: StepInput, session_state: dict[str, Any]) -> bool:
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
                    Step(
                        name=INTENT_ROUTER_STEP_NAME,
                        executor=_agent_executor_factory(
                            agent=single_agent,
                            include_summary=True
                        )
                    ),
                    name="Feedback and Routing",
                ),
                remediation_check_step,
            ],
        ),
        output_step
    ],
)