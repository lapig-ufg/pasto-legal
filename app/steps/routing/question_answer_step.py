from agno.workflow import Step

from app.agents.question_answer_agent import question_answer_agent
from app.core.step_factory import _agent_executor_factory
from app.schemas.workflow_state import RouteEnum


question_answer_step = Step(
    name=RouteEnum.QUESTION_ANSWER.value,
    executor=_agent_executor_factory(
        question_answer_agent,
        include_summary=False,
        num_runs=1
    ),
)