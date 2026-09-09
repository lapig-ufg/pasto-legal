"""Tests for the prompts loader fallback behavior (English defaults).

The loader merges the localized YAML files (app/configs/prompts/*.yml) over
the English defaults (app/configs/prompts/defaults/*.yml), warning per gap.
These tests drive it with temporary directories via monkeypatched path
constants and a cleared cache.
"""

import textwrap
from pathlib import Path

import pytest
from agno.utils.log import logger as agno_logger

import semente.configs.prompts as prompts


@pytest.fixture
def prompt_dirs(tmp_path, monkeypatch):
    """Isolated prompts/ and defaults/ directories with a cleared cache.

    agno's logger does not propagate (its rich handler prints directly), so
    propagation is enabled to let caplog capture the loader warnings.
    """
    localized_dir = tmp_path / "prompts"
    defaults_dir = localized_dir / "defaults"
    localized_dir.mkdir()
    defaults_dir.mkdir()

    monkeypatch.setattr(prompts, "PROMPTS_DIR", localized_dir)
    monkeypatch.setattr(prompts, "DEFAULTS_DIR", defaults_dir)
    monkeypatch.setattr(agno_logger, "propagate", True)
    prompts._load_yaml.cache_clear()
    prompts._read_yaml.cache_clear()

    yield localized_dir, defaults_dir

    prompts._load_yaml.cache_clear()
    prompts._read_yaml.cache_clear()


def _write(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")


DEFAULT_AGENTS = """\
    my_agent:
      name: "Default Agent"
      role: "Default role."
      instructions: |
        Default instructions.
    other_agent:
      name: "Other Agent"
      instructions: |
        Other instructions.
"""

DEFAULT_TOOLS = """\
    my_tools:
      tool_one:
        description: |
          Default tool one description.
      tool_two:
        description: |
          Default tool two description.
"""

DEFAULT_HOOKS = """\
    pre_hooks:
      message_one: |
        Default hook message.
"""


def test_localized_missing_uses_default_with_warning(prompt_dirs, caplog):
    localized_dir, defaults_dir = prompt_dirs
    _write(defaults_dir / "agents.yml", DEFAULT_AGENTS)

    with caplog.at_level("WARNING"):
        config = prompts.get_agent_config("my_agent")

    assert config["name"] == "Default Agent"
    assert "agents.yml not found" in caplog.text
    assert "using English default" in caplog.text


def test_both_missing_raises(prompt_dirs):
    localized_dir, defaults_dir = prompt_dirs
    # Nothing written at all.

    try:
        prompts.get_agent_config("my_agent")
    except prompts.MissingPromptError:
        pass
    else:
        raise AssertionError("MissingPromptError expected when no files exist")


def test_localized_wins_over_default(prompt_dirs):
    localized_dir, defaults_dir = prompt_dirs
    _write(defaults_dir / "agents.yml", DEFAULT_AGENTS)
    _write(localized_dir / "agents.yml", """\
        my_agent:
          name: "Localized Agent"
          instructions: |
            Localized instructions.
    """)

    config = prompts.get_agent_config("my_agent")

    assert config["name"] == "Localized Agent"
    assert config["instructions"].strip() == "Localized instructions."
    # Missing field filled from default.
    assert config["role"] == "Default role."


def test_missing_subkey_warns_and_fills(prompt_dirs, caplog):
    localized_dir, defaults_dir = prompt_dirs
    _write(defaults_dir / "agents.yml", DEFAULT_AGENTS)
    _write(localized_dir / "agents.yml", """\
        my_agent:
          name: "Localized Agent"
    """)

    with caplog.at_level("WARNING"):
        config = prompts.get_agent_config("my_agent")

    assert config["instructions"].strip() == "Default instructions."
    assert "my_agent.instructions" in caplog.text
    assert "falling back to English default" in caplog.text


def test_blank_subkey_falls_back(prompt_dirs, caplog):
    localized_dir, defaults_dir = prompt_dirs
    _write(defaults_dir / "tools.yml", DEFAULT_TOOLS)
    _write(localized_dir / "tools.yml", """\
        my_tools:
          tool_one:
            description: |
              Localized tool one.
          tool_two:
            description: ""
    """)

    with caplog.at_level("WARNING"):
        description = prompts.get_tool_description("my_tools", "tool_two")

    assert description == "Default tool two description."
    assert "my_tools.tool_two" in caplog.text


def test_unknown_key_warns_but_is_ignored(prompt_dirs, caplog):
    localized_dir, defaults_dir = prompt_dirs
    _write(defaults_dir / "agents.yml", DEFAULT_AGENTS)
    _write(localized_dir / "agents.yml", """\
        my_agent:
          name: "Localized Agent"
          instrutions: |
            Ooops, typo.
    """)

    with caplog.at_level("WARNING"):
        config = prompts.get_agent_config("my_agent")

    assert config["name"] == "Localized Agent"
    assert "instrutions" in caplog.text
    # The typo'd key is not part of the merged config.
    assert "instrutions" not in config


def test_unknown_top_level_agent_warns(prompt_dirs, caplog):
    localized_dir, defaults_dir = prompt_dirs
    _write(defaults_dir / "agents.yml", DEFAULT_AGENTS)
    _write(localized_dir / "agents.yml", """\
        my_agent:
          name: "Localized Agent"
          instructions: |
            Localized.
        welcomingagent:
          name: "Typo Agent"
    """)

    with caplog.at_level("WARNING"):
        prompts.get_agent_config("my_agent")

    assert "welcomingagent" in caplog.text


def test_unknown_agent_raises(prompt_dirs):
    localized_dir, defaults_dir = prompt_dirs
    _write(defaults_dir / "agents.yml", DEFAULT_AGENTS)

    try:
        prompts.get_agent_config("not_there")
    except prompts.MissingPromptError:
        pass
    else:
        raise AssertionError("MissingPromptError expected for unknown agent")


def test_hooks_group_merge(prompt_dirs, caplog):
    localized_dir, defaults_dir = prompt_dirs
    _write(defaults_dir / "hooks.yml", DEFAULT_HOOKS)
    _write(localized_dir / "hooks.yml", """\
        pre_hooks:
          message_one: "Localized message."
    """)

    with caplog.at_level("WARNING"):
        texts = prompts.get_hook_texts("pre_hooks")

    assert texts["message_one"] == "Localized message."
    # hooks.yml has only one level of nesting; single-level keys are merged as
    # scalars, so nothing is missing here and no warning fires.
    assert "falling back" not in caplog.text


def test_no_warning_when_localized_is_complete(prompt_dirs, caplog):
    localized_dir, defaults_dir = prompt_dirs
    _write(defaults_dir / "agents.yml", DEFAULT_AGENTS)
    _write(localized_dir / "agents.yml", """\
        my_agent:
          name: "Localized Agent"
          role: "Localized role."
          instructions: |
            Localized instructions.
        other_agent:
          name: "Localized Other"
          instructions: |
            Localized other.
    """)

    with caplog.at_level("WARNING"):
        config = prompts.get_agent_config("my_agent")

    assert config["name"] == "Localized Agent"
    assert "[prompts]" not in caplog.text


def test_caching_loads_files_once(prompt_dirs, caplog):
    localized_dir, defaults_dir = prompt_dirs
    _write(defaults_dir / "agents.yml", DEFAULT_AGENTS)

    with caplog.at_level("WARNING"):
        prompts.get_agent_config("my_agent")
        prompts.get_agent_config("my_agent")
        prompts.get_agent_config("other_agent")

    # One warning for the missing localized file, not one per access.
    assert caplog.text.count("agents.yml not found") == 1