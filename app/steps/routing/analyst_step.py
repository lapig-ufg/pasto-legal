from agno.workflow import Step

from app.agents.analyst_agent import analyst_agent
from app.core.step_factory import _agent_executor_factory
from app.schemas.workflow_state import RouteEnum

analyst_step = Step(
    name=RouteEnum.ANALYST.value,
    executor=_agent_executor_factory(analyst_agent),
)