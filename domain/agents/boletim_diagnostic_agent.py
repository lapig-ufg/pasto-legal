from semente.backends.base import AgentSpec
from semente.backends.registry import get_backend
from semente.configs.prompts import get_agent_config


_boletim_diagnostic_config = get_agent_config("boletim_diagnostic_agent")


boletim_diagnostic_agent = get_backend().build_agent(
    AgentSpec(
        name=_boletim_diagnostic_config["name"],
        instructions=lambda run_context: _boletim_diagnostic_config["instructions"].strip(),
    )
)