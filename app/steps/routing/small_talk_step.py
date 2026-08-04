from agno.workflow import Step

from app.agents.small_talk_agents import small_talk_agent
from app.core.step_factory import _agent_executor_factory
from app.schemas.workflow_state import RouteEnum

small_talk_step = Step(
    name=RouteEnum.SMALL_TALK.value,
    executor=_agent_executor_factory(
        small_talk_agent,
        include_summary=False,
        num_runs=1
    ),
)