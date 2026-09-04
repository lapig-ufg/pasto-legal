from agno.agent import Agent
from agno.run import RunContext

from app.configs.config import config
from app.configs.prompts import get_agent_config
from app.schemas.user_persona import PersonaUpdate, UserPersona


_persona_config = get_agent_config("persona_agent")


def get_instructions(run_context: RunContext) -> str:
    session_state = run_context.session_state

    user_persona_dict = session_state.get("user_persona", {})
    user_persona = UserPersona.model_validate(user_persona_dict)

    negative_prompt = ""
    user_satisfaction = session_state.get("user_satisfaction")
    if user_satisfaction and user_satisfaction.level == 1:
        if user_satisfaction.approved:
            negative_prompt = _persona_config["negative_prompt_approved"].strip().format(
                new_message=user_satisfaction.new_message
            )
        else:
            negative_prompt = _persona_config["negative_prompt_rejected"].strip().format(
                new_message=user_satisfaction.new_message
            )

    instructions = _persona_config["instructions"].strip().format(
        user_persona=str(user_persona),
        satisfaction_level=user_satisfaction.level_message if user_satisfaction else 'Não informado',
        last_message=session_state.messages.last_message if hasattr(session_state, 'messages') else '',
        negative_prompt=negative_prompt,
    )

    return instructions


persona_manager_agent = Agent(
    name=_persona_config["name"],
    model=config.model,
    fallback_models=[config.fallback_model],
    instructions=get_instructions,
    output_schema=PersonaUpdate,
    use_json_mode=True,
    debug_mode=config.DEBUG_MODE,
)