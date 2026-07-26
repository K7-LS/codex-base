from __future__ import annotations

import tomllib

from codex_base.migrate import (
    convert_agent_source,
    convert_skill_source,
    materialize_legacy,
)


def test_agent_conversion_removes_client_coupling_and_fixed_model():
    """Catches a native agent that still depends on Claude runtime vocabulary."""
    source = """---
name: auditor
model: sonnet
description: legacy description
tools: Read, Task, AskUserQuestion, mcp__word__get_document_text
---
Основному Claude нужно вызвать Task и затем AskUserQuestion.
Читайте ~/.claude/memory/reference.md через mcp__word__get_document_text.
"""
    metadata = {
        "id": "auditor",
        "name": "auditor",
        "description": "Независимо проверяет результат.",
        "permission_class": "ro",
        "required_capabilities": ["core.files.read", "document.word.read"],
    }

    rendered = convert_agent_source(source, metadata)
    parsed = tomllib.loads(rendered)

    assert parsed["name"] == "auditor"
    assert parsed["description"] == metadata["description"]
    assert parsed["sandbox_mode"] == "read-only"
    assert "model" not in parsed
    assert "model_reasoning_effort" not in parsed
    instructions = parsed["developer_instructions"]
    for forbidden in (
        ".claude",
        "CLAUDE.md",
        "AskUserQuestion",
        "mcp__",
        "основному Claude",
    ):
        assert forbidden not in instructions
    assert "custom agent" in instructions
    assert "document.word.read" in instructions


def test_skill_conversion_replaces_discovery_metadata_and_native_paths():
    """Catches verbose legacy frontmatter and a Claude-only skill install path."""
    source = """---
name: sample
description: A very long legacy process summary
---
# Sample

Read `~/.claude/skills/sample/SKILL.md`, then use AskUserQuestion.
"""
    metadata = {
        "name": "sample",
        "description": "Use when a sample migration is required.",
    }

    rendered = convert_skill_source(source, metadata)

    assert rendered.startswith("---\nname: sample\n")
    assert metadata["description"] in rendered
    assert "~/.agents/skills/sample/SKILL.md" in rendered
    assert "AskUserQuestion" not in rendered
    assert "request_user_input" in rendered


def test_materialize_copies_supporting_assets_and_converts_entrypoints(tmp_path):
    """Catches imports that preserve SKILL.md but silently drop tools or references."""
    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    (legacy / "agents").mkdir(parents=True)
    (legacy / "skills" / "sample" / "tools").mkdir(parents=True)
    (legacy / "memory").mkdir()
    (legacy / "agents" / "auditor.md").write_text(
        "---\nname: auditor\n---\nRead the source.\n",
        encoding="utf-8",
    )
    (legacy / "skills" / "sample" / "SKILL.md").write_text(
        "---\nname: sample\ndescription: legacy\n---\nUse the helper.\n",
        encoding="utf-8",
    )
    (legacy / "skills" / "sample" / "tools" / "helper.ps1").write_text(
        "Write-Output '~/.claude/skills/sample'\n",
        encoding="utf-8",
    )
    (legacy / "skills" / "sample" / "README.md").write_text(
        "Use ~/.claude/skills/sample and AskUserQuestion via "
        "mcp__word__get_document_text.\n",
        encoding="utf-8",
    )
    (legacy / "skills" / "sample" / "tests").mkdir()
    (legacy / "skills" / "sample" / "tests" / "test_legacy.py").write_text(
        "raise AssertionError('must not ship')\n",
        encoding="utf-8",
    )
    (legacy / "memory" / "reference.md").write_text("# Reference\n", encoding="utf-8")
    catalog = {
        "agents": [
            {
                "id": "auditor",
                "name": "auditor",
                "description": "Checks results.",
                "source": "agents/auditor.toml",
                "permission_class": "ro",
                "required_capabilities": ["core.files.read"],
            }
        ],
        "skills": [
            {
                "id": "sample",
                "name": "sample",
                "description": "Use when a sample is needed.",
                "source": "skills/sample/SKILL.md",
                "required_capabilities": [],
            }
        ],
    }
    cold = {"memory": ["memory/reference.md"], "chains": [], "commands": []}

    materialize_legacy(legacy, target, catalog, cold)

    assert (target / "agents" / "auditor.toml").is_file()
    assert (target / "skills" / "sample" / "SKILL.md").is_file()
    assert (
        target / "skills" / "sample" / "tools" / "helper.ps1"
    ).read_text(encoding="utf-8") == "Write-Output '~/.agents/skills/sample'\n"
    readme = (target / "skills" / "sample" / "README.md").read_text(
        encoding="utf-8"
    )
    assert ".claude" not in readme
    assert "AskUserQuestion" not in readme
    assert "mcp__" not in readme
    assert not (target / "skills" / "sample" / "tests").exists()
    assert (target / "cold" / "memory" / "reference.md").is_file()


def test_materialize_applies_native_skill_override_and_prune_list(tmp_path):
    """Catches unsupported legacy helpers surviving beneath a native skill facade."""
    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    (legacy / "agents").mkdir(parents=True)
    (legacy / "skills" / "sample" / "tools" / "hooks").mkdir(parents=True)
    (legacy / "agents" / "auditor.md").write_text(
        "---\nname: auditor\n---\nRead.\n",
        encoding="utf-8",
    )
    (legacy / "skills" / "sample" / "SKILL.md").write_text(
        "---\nname: sample\ndescription: legacy\n---\nLegacy body.\n",
        encoding="utf-8",
    )
    (legacy / "skills" / "sample" / "tools" / "hooks" / "legacy.ps1").write_text(
        "Write-Output legacy\n",
        encoding="utf-8",
    )
    override = target / "native-overrides" / "skills" / "sample"
    override.mkdir(parents=True)
    (override / ".remove.json").write_text(
        '["tools/hooks"]\n',
        encoding="utf-8",
    )
    (override / "SKILL.md").write_text(
        "---\nname: sample\ndescription: native\n---\nNative Codex body.\n",
        encoding="utf-8",
    )
    catalog = {
        "agents": [
            {
                "id": "auditor",
                "name": "auditor",
                "description": "Checks results.",
                "source": "agents/auditor.toml",
                "permission_class": "ro",
                "required_capabilities": [],
            }
        ],
        "skills": [
            {
                "id": "sample",
                "name": "sample",
                "description": "Use when a sample is needed.",
                "source": "skills/sample/SKILL.md",
                "required_capabilities": [],
            }
        ],
    }

    materialize_legacy(
        legacy,
        target,
        catalog,
        {"memory": [], "chains": [], "commands": []},
    )

    assert not (target / "skills" / "sample" / "tools" / "hooks").exists()
    skill = (target / "skills" / "sample" / "SKILL.md").read_text(encoding="utf-8")
    assert "Native Codex body." in skill
    assert "Legacy body." not in skill
    assert not (target / "skills" / "sample" / ".remove.json").exists()
