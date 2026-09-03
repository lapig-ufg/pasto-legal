"""Loader for externalized LLM-facing texts (agents, tools, hooks).

The YAML files under ``app/configs/prompts/`` are the single runtime source for
agent instructions/metadata and tool descriptions, so the product can be
re-localized to other languages by replacing these files (no code changes).

Structure:
    agents.yml -> {agent_tag: {name/role/description/instructions/...}}
    tools.yml  -> {component: {tool_name: {description: ...}}}
    hooks.yml  -> {group: {key: text}} or {group: {key: {subkey: text}}}
"""

from functools import lru_cache
from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class MissingPromptError(KeyError):
    """Raised when a requested agent/tool/hook text is absent from the YAML files."""


@lru_cache(maxsize=1)
def _load_yaml(filename: str) -> dict:
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise MissingPromptError(f"Prompts file not found: {path}")
    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise MissingPromptError(f"Prompts file must contain a mapping: {path}")
    return data


def get_agent_config(agent: str) -> dict:
    """Returns the full YAML mapping for one agent tag (e.g. 'single_agent')."""
    agents = _load_yaml("agents.yml")
    if agent not in agents:
        raise MissingPromptError(f"Agent '{agent}' not found in agents.yml")
    if not isinstance(agents[agent], dict):
        raise MissingPromptError(f"Agent '{agent}' must be a mapping in agents.yml")
    return agents[agent]


def get_agent_field(agent: str, field: str) -> str:
    agent_config = get_agent_config(agent)
    if field not in agent_config or agent_config[field] is None:
        raise MissingPromptError(f"Field '{field}' missing for agent '{agent}' in agents.yml")
    return str(agent_config[field])


def get_tool_description(component: str, tool_name: str) -> str:
    """Returns the runtime description of one tool from tools.yml.

    ``component`` is the tool file (e.g. 'weather_tools'), ``tool_name`` the
    function name (e.g. 'get_monthly_precipitation_forecast').
    """
    tools = _load_yaml("tools.yml")
    component_tools = tools.get(component)
    if not isinstance(component_tools, dict) or tool_name not in component_tools:
        raise MissingPromptError(
            f"Tool '{component}.{tool_name}' not found in tools.yml"
        )
    entry = component_tools[tool_name]
    if isinstance(entry, dict):
        description = entry.get("description")
    else:
        description = entry
    if not description:
        raise MissingPromptError(
            f"Tool '{component}.{tool_name}' has an empty description in tools.yml"
        )
    return str(description).strip()


def get_hook_texts(group: str) -> dict:
    """Returns all texts of one hook group (e.g. 'pre_hooks')."""
    hooks = _load_yaml("hooks.yml")
    if group not in hooks:
        raise MissingPromptError(f"Hook group '{group}' not found in hooks.yml")
    if not isinstance(hooks[group], dict):
        raise MissingPromptError(f"Hook group '{group}' must be a mapping in hooks.yml")
    return hooks[group]


def get_hook_text(group: str, key: str) -> str:
    texts = get_hook_texts(group)
    if key not in texts or texts[key] is None:
        raise MissingPromptError(f"Hook text '{group}.{key}' not found in hooks.yml")
    return str(texts[key]).strip()