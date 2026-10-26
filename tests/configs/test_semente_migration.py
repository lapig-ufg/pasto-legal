"""Smoke tests for the Semente-main migration.

They guard the manifest/prompt wiring that is easy to break when the framework
changes: the interaction-assessment feature name, the terms-acceptance file,
and the welcoming-agent placeholders.
"""

from pathlib import Path

import yaml

from semente.manifest import Manifest

ROOT = Path(__file__).resolve().parents[2]


def test_manifest_uses_semente_main_features():
    raw = yaml.safe_load((ROOT / "semente.yaml").read_text(encoding="utf-8"))

    assert "feedback_workflow" not in raw["features"]
    assert raw["features"]["interaction-assessment"] is True

    manifest = Manifest.load(ROOT / "semente.yaml")
    assert manifest.features["interaction-assessment"].enable is True

    terms = manifest.features["terms-acceptance"]
    assert terms.enable is True
    assert terms.url == "https://pasto.legal/termos-de-uso"
    assert (manifest.source_dir / terms.file).is_file()


def test_welcoming_prompts_use_the_terms_feature():
    agents = yaml.safe_load((ROOT / "domain/prompts/agents.yml").read_text(encoding="utf-8"))
    welcoming = agents["welcoming_agent"]

    assert "terms_text" not in welcoming
    assert "{app_name}" in welcoming["instructions"]
    assert "{terms_link_instruction}" in welcoming["instructions"]
    assert "{terms_text}" in welcoming["instructions"]
    assert "instructions_persona" in welcoming
    assert "{terms_closed_note}" in welcoming["instructions_persona"]
    assert welcoming["persona_not_informed"]

    hooks = yaml.safe_load((ROOT / "domain/prompts/hooks.yml").read_text(encoding="utf-8"))
    assert "missing_required_state" in hooks["tool_hooks"]
    assert "no_property_selected" not in hooks["tool_hooks"]
