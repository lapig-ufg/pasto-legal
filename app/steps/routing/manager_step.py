"""Manager route step: runs the manager agent and, when it just registered a
property, triggers the first diagnosis pipeline (geospatial data extraction
followed by the diagnosis agent) before resetting the workflow route.

External interface:
    manager_step  -- Steps instance consumed by the main workflow.
"""

from typing import Any, Dict

from agno.utils.log import log_error
from agno.workflow import Condition, Step, Steps
from agno.workflow.types import StepInput, StepOutput

from app.agents.diagnosis_agent import diagnosis_agent
from app.agents.manager_agent import manager_agent
from app.core.step_factory import _agent_executor_factory
from app.schemas.property_stats import PastureStats
from app.schemas.rural_property import RuralProperty
from app.schemas.workflow_state import RouteEnum, WorkflowState
from app.services.geospatial.gee import query_pasture_statistics

# Geospatial observation window used for the first diagnosis.
_OBSERVATION_YEAR = 2026
_OBSERVATION_MONTH = 5

# User-facing message reused across failure paths.
_FAILURE_MESSAGE = (
    "Desculpa, houve um erro durante a execução. Tente novamente mais tarde!"
)


def _last_output(step_input: StepInput) -> StepOutput:
    """Return the most recent previous-step output, falling back to an empty
    one when none are available (keeps passthrough steps resilient)."""
    outputs = step_input.previous_step_outputs or {}
    if not outputs:
        return StepOutput(content="")
    return list(outputs.values())[-1]


def _first_diagnosis_evaluator(
    step_input: StepInput, session_state: Dict[str, Any]
) -> bool:
    """Return True when property registration finished and the first
    diagnosis should run."""
    workflow_state = session_state.get("workflow_state") or {}
    return workflow_state.get("route") == RouteEnum.DIAGNOSIS


def _feature_data_extraction(
    step_input: StepInput, session_state: Dict[str, Any]
) -> StepOutput:
    """Extract pasture statistics for the most recently registered property
    and forward them as the next step's input."""
    all_properties = session_state.get("all_properties") or []
    if not all_properties:
        log_error("_feature_data_extraction: no registered property available.")
        return StepOutput(content=_FAILURE_MESSAGE, stop=True, success=False)

    try:
        prop = RuralProperty.model_validate(all_properties[-1])
    except Exception as exc:
        log_error(f"_feature_data_extraction: invalid property data: {exc}")
        return StepOutput(content=_FAILURE_MESSAGE, stop=True, success=False)

    try:
        pasture_stats: PastureStats = query_pasture_statistics(
            prop.get_coords(), _OBSERVATION_YEAR, _OBSERVATION_MONTH
        )
    except Exception as exc:
        log_error(f"_feature_data_extraction: geospatial query failed: {exc}")
        return StepOutput(content=_FAILURE_MESSAGE, stop=True, success=False)

    return StepOutput(content=str(pasture_stats))


def _update_workflow_state_executor(
    step_input: StepInput, session_state: Dict[str, Any]
) -> StepOutput:
    """Reset the workflow route to AUTO after the first diagnosis and pass
    the previous step's output through unchanged."""
    raw_state = session_state.get("workflow_state")
    try:
        workflow_state = WorkflowState.model_validate(raw_state or {})
    except Exception as exc:
        log_error(f"_update_workflow_state_executor: invalid workflow_state: {exc}")
        workflow_state = WorkflowState()

    workflow_state.route = RouteEnum.AUTO
    session_state["workflow_state"] = workflow_state.model_dump()

    return _last_output(step_input)


manager_step = Steps(
    name=RouteEnum.MANAGER.value,
    steps=[
        Step(
            name="Manager Run",
            executor=_agent_executor_factory(
                manager_agent,
                include_summary=False,
                num_runs=1,
            ),
        ),
        Condition(
            name="Check First Diagnosis",
            evaluator=_first_diagnosis_evaluator,
            steps=[
                Step(
                    name="Feature Data Extraction",
                    executor=_feature_data_extraction,
                ),
                Step(
                    name="Run Diagnosis",
                    executor=_agent_executor_factory(
                        diagnosis_agent,
                        include_summary=False,
                    ),
                ),
                Step(
                    name="Workflow Route Update",
                    executor=_update_workflow_state_executor,
                ),
            ],
            else_steps=[
                Step(
                    name="Skip Diagnosis",
                    executor=_last_output,
                ),
            ],
        ),
    ],
)