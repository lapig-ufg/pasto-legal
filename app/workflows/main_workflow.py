from typing import Any, Dict

from agno.workflow import Workflow, Step, Parallel, Condition, Router
from agno.workflow.types import StepInput, StepOutput

from app.agents import (
    question_answer_agent,
    manager_agent,
    analyst_agent,
    router_agent,
    small_talk_agent
)
from app.database.agno_db import db
from app.workflows.feedback_workflow import feedback_workflow, merge_output_step


#====================================
#
#====================================
def greetings_evaluator(step_input: StepInput, session_state: Dict[str, Any]):
    is_greeted = session_state.get("is_greeted", False)

    if is_greeted:
        return True
    else:
        session_state["is_greeted"] = True
        return False


def greetings_executor(step_input: StepInput):
    return StepOutput(content="Olá, seja bem-vindo ao Pato Legal. Como posso te ajudar hoje?")

#====================================
#
#====================================
def agent_router_selector(step_input: StepInput, session_state: Dict[str, Any]) -> str:
    """
    Selector do roteador que executa o Router Agent e direciona o fluxo 
    para o agente especialista correto com base na intenção do usuário.
    """
    workflow_route = session_state.get("workflow_route", None)
    if workflow_route:
        return workflow_route

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


pasto_legal_workflow = Workflow(
    name="Pasto Legal Workflow",
    steps=[
        Condition(
            name="Greetings Condition",
            evaluator=greetings_evaluator,
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
                        selector=agent_router_selector,
                        choices=[
                            Step(
                                name="default",
                                executor=lambda x: None
                            ),
                            Step(
                                name="property_analyst_agent",
                                agent=analyst_agent
                            ),
                            Step(
                                name="property_manager_agent",
                                agent=manager_agent
                            ),
                            Step(
                                name="question_answer_agent",
                                agent=question_answer_agent
                            ),
                            Step(
                                name="small_talk_agent",
                                agent=small_talk_agent
                            )
                        ]
                    )
                ),
                merge_output_step
            ]
        )
    ],
    db=db
)