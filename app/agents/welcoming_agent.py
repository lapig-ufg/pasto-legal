from agno.agent import Agent

from app.configs.config import config
from app.configs.prompts import get_agent_config
from app.tools.tts_tools import generate_speech
from app.tools.onboarding_tools import accept_terms_and_conditions


_welcoming_config = get_agent_config("welcoming_agent")


welcoming_agent = Agent(
    name=_welcoming_config["name"],
    role=_welcoming_config["role"],
    description=_welcoming_config["description"],
    instructions=_welcoming_config["instructions"].strip().format(
        terms_text=_welcoming_config["terms_text"].strip()
    ),
    tools=[
        generate_speech,
        accept_terms_and_conditions
    ],
    model=config.model,
    fallback_models=[config.fallback_model],
    debug_mode=config.DEBUG_MODE
)