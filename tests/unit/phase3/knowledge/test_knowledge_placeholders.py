from pathlib import Path
from string import Template

import pytest

from phase3.knowledge.knowledge_loader import KnowledgeLoader

PLACEHOLDER_WHITELIST = {
    "entity_id",
    "cloud_provider",
    "region",
    "final_score",
    "severity",
    "deviation_score",
    "drift_score",
    "similarity_score",
    "group_size",
    "top_changed_feature",
}


def test_knowledge_base_placeholders_are_whitelisted():
    knowledge_path = (
        Path(__file__).resolve().parents[4]
        / "phase3"
        / "knowledge"
        / "knowledge_base.yaml"
    )
    content = knowledge_path.read_text(encoding="utf-8")
    placeholders = {
        match.group("named") or match.group("braced")
        for match in Template.pattern.finditer(content)
        if match.group("named") or match.group("braced")
    }

    assert placeholders <= PLACEHOLDER_WHITELIST


def test_loader_rejects_non_whitelisted_placeholders(tmp_path):
    knowledge_path = (
        Path(__file__).resolve().parents[4]
        / "phase3"
        / "knowledge"
        / "knowledge_base.yaml"
    )
    malformed = knowledge_path.read_text(encoding="utf-8").replace(
        "${entity_id}", "${tenant_id}", 1
    )
    fixture = tmp_path / "knowledge_base.yaml"
    fixture.write_text(malformed, encoding="utf-8")

    with pytest.raises(ValueError, match="unapproved placeholder"):
        KnowledgeLoader(fixture)
