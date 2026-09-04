from agno.agent import Agent
from agno.run import RunContext

from app.configs.config import config
from app.configs.prompts import get_agent_config
from app.schemas.user_mood import Effectiveness


_remediation_config = get_agent_config("remediation_agent")
_satisfaction_config = get_agent_config("satisfaction_agent")

#============================================================
#
#============================================================
remediation_agent = Agent(
    name=_remediation_config["name"],
    model=config.model,
    instructions=_remediation_config["instructions"].strip(),
    debug_mode=config.DEBUG_MODE,
)


#============================================================
#
#============================================================
def get_satisfaction_instructions(run_context: RunContext) -> str:
    session_state = run_context.session_state or {}
    user_mood_dict = session_state.get("user_mood", None)

    base_instructions = _satisfaction_config["base_instructions"].strip()

    if user_mood_dict is None:
        scenario_text = _satisfaction_config["scenario_initial"].strip()
    else:
        scenario_text = _satisfaction_config["scenario_remediation"].strip()

    return f"{base_instructions}\n\n{scenario_text}"


satisfaction_evaluation_agent = Agent(
    name=_satisfaction_config["name"],
    model=config.model,
    fallback_models=[config.fallback_model],
    output_schema=Effectiveness,
    instructions=get_satisfaction_instructions,
    debug_mode=config.DEBUG_MODE,
)