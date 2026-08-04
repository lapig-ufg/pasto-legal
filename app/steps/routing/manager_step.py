from typing import Any, Dict

from agno.workflow import Condition, Step, Steps
from agno.workflow.types import StepInput, StepOutput

from app.agents.diagnosis_agent import diagnosis_agent
from app.agents.manager_agent import manager_agent
from app.core.step_factory import _agent_executor_factory
from app.schemas.property_stats import PastureStats
from app.schemas.rural_property import RuralProperty
from app.schemas.workflow_state import RouteEnum
from app.services.geospatial.gee import query_pasture_statistics


def _first_diagnosis_evaluator(step_input: StepInput, session_state: Dict[str, Any]):
    """Verify if the property registration ended sucefully and should run the first diagnosis"""
    return session_state.get("workflow_state", {}).get("route") == RouteEnum.DIAGNOSIS


def _feature_data_extraction(step_input: StepInput, session_state: Dict[str, Any]):
    all_properties = session_state.get("all_properties", [])
    if not all_properties:
        return StepOutput(
            content="Desculpa, houve um erro durante a execução. Tente novamente mais tarde!",
            stop=True,
            success=False
        )
    
    prop = RuralProperty.model_validate(all_properties[-1])
    
    pasture_stats: PastureStats = query_pasture_statistics(prop.get_coords(), 2026, 5)

    return StepOutput(
        content=str(pasture_stats)
    )

def _update_workflow_state_executor(step_input: StepInput, session_state: Dict[str, Any]):
    workflow_state = WorkflowState.model_validate(session_state.get("workflow_state"))
    workflow_state.route = RouteEnum.AUTO
    session_state["workflow_state"] = workflow_state.dump()

    return list(step_input.previous_step_outputs.values())[-1]


manager_step = Steps(
    name=RouteEnum.MANAGER.value,
    steps=[
        Step(
            name="Manager Run",
            executor=_agent_executor_factory(
                manager_agent,
                include_summary=False,
                num_runs=1
            ),
        ),
        Condition(
            name="Check First Diagnosis",
            evaluator=_first_diagnosis_evaluator,
            steps=[
                Step(
                    name="Feature Data Extraction",
                    executor=_feature_data_extraction
                ),
                Step(
                    name="Run Diagnosis",
                    executor=_agent_executor_factory(
                        diagnosis_agent,
                        include_summary=False
                    )
                ),
                Step(
                    name="Workflow Route Update",
                    executor=_update_workflow_state_executor
                )
            ],
            else_steps=[
                Step(
                    name="Skip Diagnosis",
                    executor=lambda step_input: list(step_input.previous_step_outputs.values())[-1]
                )
            ]
        )
    ]
)