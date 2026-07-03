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


def check_loop_end_condition(step_outputs: List[StepOutput]) -> bool:
    """Checks the last step output to determine if the loop should terminate."""
    if not step_outputs:
        return True
        
    last_step_output = step_outputs[-1]
    print("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",)
    print(last_step_output.content, flush=True)
    return last_step_output.content.get("should_stop", True)


def evaluate_loop_status(step_input: StepInput, session_state: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluates whether the router loop should continue based on the workflow state."""
    last_step_output = step_input.get_step_output("Agent Router")
    
    raw_state = session_state.get("workflow_state", {})
    workflow_state = WorkflowState.model_validate(raw_state)
    
    is_loop_active = workflow_state.is_loop_active
    should_stop = not is_loop_active

    return StepOutput(
        content={
            "should_stop": should_stop, 
            "step_output": last_step_output
        }
    )


def unpacker_executor(step_input: StepInput) -> Any:
    """
    Robust unpacker that handles three state contexts:
    1. First loop entry: passes the raw initial text/content forward.
    2. Loop iteration back: unpacks the dictionary from the previous Loop Evaluator Step.
    3. Loop exit: unpacks the final result from the Agents Loop to feed the next pipeline steps.
    """
    last_step_output = [step_input.previous_step_outputs.values()][-1]

    if last_step_output is None:
        return step_input.input
        
    return step_input.input
    

# --- Workflow Definition ---

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
                    Steps(
                        name="Agent Processing Pipeline",
                        steps=[
                            Loop(
                                name="Agents Loop",
                                end_condition=check_loop_end_condition,
                                forward_iteration_output=True,
                                steps=[
                                    Step(
                                        name="Loop Unpacker Step",
                                        executor=unpacker_executor
                                    ),
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
                                    Step(
                                        name="Loop Evaluator Step", 
                                        executor=evaluate_loop_status
                                    )
                                ]
                            ),
                            Step(
                                name="Unpacker Step",
                                executor=unpacker_executor
                            )
                        ]
                    )
                ),
                merge_output_step
            ]
        )
    ]
)