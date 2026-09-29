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
from agno.workflow import Condition, Parallel, Step

from app.agents.single_agent import single_agent
from app.agents.welcoming_agent import welcoming_agent
from app.configs.config import config
from app.core.step_factory import _agent_executor_factory
from app.database.agno_db import db
from app.models.persist_on_success_workflow import PersistOnSuccessWorkflow
from app.steps.feedback.remediation import remediation_check_step, INTENT_ROUTER_STEP_NAME
from app.steps.guardrails_step import guardrails_step
from app.steps.input_step import input_step
from app.steps.output_step import output_step
from app.steps.summarization_step import summarization_step
from app.workflows.feedback_workflow import feedback_workflow
from app.workflows.onboarding_gate import _needs_onboarding


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