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

from agno.workflow import Condition, Parallel, Router, Step

from app.agents import (
    analyst_agent,
    manager_agent,
    question_answer_agent,
    small_talk_agent,
)
from app.agents.welcoming_agent import welcoming_agent
from app.configs.config import config
from app.core.persist_on_success_workflow import PersistOnSuccessWorkflow
from app.core.session_state import WorkflowRouteEnum
from app.core.step_factory import _agent_executor_factory
from app.database.agno_db import db
from app.steps.feedback.remediation import remediation_check_step
from app.steps.input.final_output import _final_output
from app.steps.input.guardrail_pii import _guardrail_pii_executor
from app.steps.input.input_processing import _input_processing_executor
from app.steps.routing.needs_onboarding import _needs_onboarding
from app.steps.routing.route_selector import _route_selector
from app.workflows.feedback_workflow import feedback_workflow
from app.workflows.summarization_workflow import summarization_workflow


pasto_legal_workflow = PersistOnSuccessWorkflow(
    name="Pasto Legal Workflow",
    db=db,
    debug_mode=config.DEBUG_MODE,
    add_workflow_history_to_steps=True,
    num_history_runs=1,
    steps=[
        Step(
            name="Input Processing",
            executor=_input_processing_executor,
        ),
        Step(
            name="Guardrail PII",
            executor=_guardrail_pii_executor,
        ),
        Condition(
            name="Onboarding Check",
            evaluator=_needs_onboarding,
            steps=[
                Step(
                    name="Welcoming Agent",
                    executor=_agent_executor_factory(welcoming_agent),
                ),
            ],
            else_steps=[
                Parallel(
                    summarization_workflow,
                    feedback_workflow,
                    Router(
                        name="Intent Router",
                        selector=_route_selector,
                        choices=[
                            Step(
                                name="default",
                                executor=lambda step_input: None,
                            ),
                            Step(
                                name=WorkflowRouteEnum.ANALYST.value,
                                executor=_agent_executor_factory(analyst_agent),
                            ),
                            Step(
                                name=WorkflowRouteEnum.MANAGER.value,
                                executor=_agent_executor_factory(manager_agent, summary=False, num_runs=1),
                            ),
                            Step(
                                name=WorkflowRouteEnum.QUESTION_ANSWER.value,
                                executor=_agent_executor_factory(question_answer_agent, summary=False, num_runs=1),
                            ),
                            Step(
                                name=WorkflowRouteEnum.SMALL_TALK.value,
                                executor=_agent_executor_factory(small_talk_agent, summary=False, num_runs=1),
                            ),
                        ],
                    ),
                    name="Feedback and Routing",
                ),
                remediation_check_step,
            ],
        ),
        Step(
            name="Final Output",
            executor=_final_output,
        ),
    ],
)