# from agno.agent import Agent
# 
# from app.configs.config import config
# from app.configs.prompts import get_agent_config
# 
# 
# _boletim_diagnostic_config = get_agent_config("boletim_diagnostic_agent")
# 
# 
# def get_instructions() -> str:
#     return _boletim_diagnostic_config["instructions"].strip()
# 
# 
# boletim_diagnostic_agent = Agent(
#     name=_boletim_diagnostic_config["name"],
#     model=config.model,
#     fallback_models=[config.fallback_model],
#     instructions=get_instructions,
# )