from typing import Any, Dict, List

from agno.utils.log import log_debug
from agno.workflow import Workflow, Step, Steps, Parallel, Condition, Router, Loop
from agno.workflow.types import StepInput, StepOutput

from app.agents import (
    question_answer_agent,
    manager_agent,
    analyst_agent,
    router_agent,
    small_talk_agent
)
from app.database.agno_db import db
from app.utils.interfaces.workflow_state import WorkflowState, WorkflowRouteEnum
from app.workflows.feedback_workflow import feedback_workflow, merge_output_step


#====================================
#
#====================================
def is_greetings_evaluator(step_input: StepInput, session_state: Dict[str, Any]):
    workflow_state_dict = session_state.get("workflow_state", None)

    if workflow_state_dict is None:
        session_state["workflow_state"] = WorkflowState().model_dump()
        return True

    return False


def greetings_executor(step_input: StepInput):
    return StepOutput(content="Olá, seja bem-vindo ao Pato Legal. Como posso te ajudar hoje?")

#====================================
#
#====================================
def workflow_route_selector(step_input: StepInput, session_state: Dict[str, Any]) -> str:
    """
    Selector do roteador que executa o Router Agent e direciona o fluxo 
    para o agente especialista correto com base na intenção do usuário.
    """
    workflow_state = WorkflowState.model_validate(session_state.get("workflow_state"))

    if not workflow_state.route is WorkflowRouteEnum.AUTO:
        return workflow_state.route.value

    try:
        user_msg = step_input.get_input_as_string()
        
        response = router_agent.run(user_msg)
        
        route_data = response.content
        
        if route_data and hasattr(route_data, "route"):
            return route_data.route
            
        if isinstance(route_data, dict) and "route" in route_data:
            return route_data["route"]
    except Exception as e:
        return 'default'
        
    return 'default'
    

# --- Workflow Definition ---

def final_response(step_input: StepInput, session_state: Dict[str, Any]):
    last_step_output: StepOutput = list(step_input.previous_step_outputs.values())[-1]
    last_response = last_step_output.steps[-1]
    print(last_response, flush=True)
    return last_response


pasto_legal_workflow = Workflow(
    name="Pasto Legal Workflow",
    db=db,
    steps=[
        Condition(
            name="Greetings Condition",
            evaluator=is_greetings_evaluator,
            steps=[
                Step(
                    name="Greetings Step",
                    executor=greetings_executor
                ) 
            ],
            else_steps=[
                Parallel(
                    feedback_workflow,
                    Router(
                        name="Agent Router",
                        selector=workflow_route_selector,
                        choices=[
                            Step(
                                name="default",
                                executor=lambda x: None
                            ),
                            Step(
                                name=WorkflowRouteEnum.ANALYST.value,
                                agent=analyst_agent
                            ),
                            Step(
                                name=WorkflowRouteEnum.MANAGER.value,
                                agent=manager_agent
                            ),
                            Step(
                                name=WorkflowRouteEnum.QUESTION_ANSWER.value,
                                agent=question_answer_agent
                            ),
                            Step(
                                name=WorkflowRouteEnum.SMALL_TALK.value,
                                agent=small_talk_agent
                            )
                        ]
                    ),
                    name="Parallel"
                ),
                merge_output_step
            ]
        ),
        Step(
            executor=final_response
        )
    ]
)