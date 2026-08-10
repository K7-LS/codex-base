from __future__ import annotations

import json
import re
import ast
import hashlib
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import yaml

from codex_base.catalog import load_catalog


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text.replace("\r\n", "\n"), re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter"
    result = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def test_native_tree_materializes_every_catalog_component(repo_root):
    """Catches catalog entries that are metadata-only and cannot be loaded by Codex."""
    catalog = load_catalog(repo_root)

    agent_files = sorted((repo_root / "agents").glob("*.toml"))
    skill_files = sorted((repo_root / "skills").glob("*/SKILL.md"))
    assert len(agent_files) == 16
    assert len(skill_files) == 38

    for item in catalog["agents"]:
        path = repo_root / str(item["source"])
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        assert parsed["name"] == item["name"]
        assert parsed["description"] == item["description"]
        assert "model" not in parsed
        assert "model_reasoning_effort" not in parsed
        if item["permission_class"] == "ro":
            assert parsed["sandbox_mode"] == "read-only"

    for item in catalog["skills"]:
        path = repo_root / str(item["source"])
        meta = _frontmatter(path.read_text(encoding="utf-8"))
        assert meta["name"] == item["name"]
        if item["id"] == "ru-writing-style":
            assert item["description"] == (
                "Use when пишешь или правишь русский текст для человека — письмо, КП, "
                "пояснительную записку, ответ экспертизе, отчёт, ТЗ, статью."
            )
            continue
        assert meta["description"] == item["description"]


def test_hot_and_warm_surfaces_are_native_and_bounded(repo_root):
    """Catches startup coupling or prompt growth before it reaches a user session."""
    hot = (repo_root / "AGENTS.md").read_text(encoding="utf-8")
    warm_paths = [repo_root / "AGENTS.md", *sorted((repo_root / "agents").glob("*.toml"))]
    skill_entrypoints = sorted((repo_root / "skills").glob("*/SKILL.md"))

    assert (len(hot.encode("utf-8")) + 2) // 3 <= 1500
    for path in warm_paths:
        text = path.read_text(encoding="utf-8")
        for pattern in (
            r"(?i)\.claude",
            r"\bCLAUDE\.md\b",
            r"@~/\.",
            r"\bAskUserQuestion\b",
            r"\bmcp__",
            r"\bsuperpowers:brainstorming\b",
        ):
            assert not re.search(pattern, text), f"{pattern} leaked into {path}"

    for path in skill_entrypoints:
        text = path.read_text(encoding="utf-8")
        for pattern in (
            r"(?i)\.claude/",
            r"\bAskUserQuestion\b",
            r"\bTaskCreate\b",
            r"\bTaskUpdate\b",
            r"\bmcp__",
        ):
            assert not re.search(pattern, text), f"{pattern} leaked into {path}"


def test_cold_catalog_is_complete_and_outside_discovery(repo_root):
    """Catches a referenced method that was omitted from the release payload."""
    cold = json.loads((repo_root / "catalog" / "cold.json").read_text(encoding="utf-8"))

    assert len(cold["memory"]) == 20
    assert len(cold["chains"]) == 3
    assert len(cold["commands"]) == 3
    for group in ("memory", "chains", "commands"):
        for relative in cold[group]:
            path = repo_root / "cold" / relative
            assert path.is_file()
            assert "skills" not in path.parts


def test_approved_ru_writing_style_and_officecli_reference_are_present(repo_root):
    """Binds the imported skill to its approved source bytes and cold-only OfficeCLI record."""
    skill = repo_root / "skills" / "ru-writing-style" / "SKILL.md"
    payload = skill.read_bytes()
    assert len(payload) == 20003
    assert hashlib.sha256(payload).hexdigest() == (
        "a20f25a852eaff976c9db90929c94f5658acb3a71eb264479f6d354e04a10938"
    )

    cold = json.loads((repo_root / "catalog" / "cold.json").read_text(encoding="utf-8"))
    reference = "memory/reference_officecli.md"
    assert reference in cold["memory"]
    assert "OfficeCLI" in (repo_root / "cold" / reference).read_text(encoding="utf-8")


def test_cold_runtime_guidance_is_codex_native_and_one_way(repo_root):
    """Catches a cold reference that reintroduces the legacy runtime or reverse sync."""
    cold_files = sorted((repo_root / "cold").glob("**/*.md"))
    assert cold_files
    for path in cold_files:
        text = path.read_text(encoding="utf-8")
        for pattern in (
            r"(?i)\.claude[/\\]",
            r"\bCLAUDE\.md\b",
            r"\bAskUserQuestion\b",
            r"\bmcp__",
        ):
            assert not re.search(pattern, text), f"{pattern} leaked into {path}"

    auto_sync = (repo_root / "cold" / "memory" / "auto_sync.md").read_text(
        encoding="utf-8"
    )
    for forbidden in ("feedback-pending", "pull-feedback", "auto-push"):
        assert forbidden not in auto_sync
    assert "hub → consumer" in auto_sync
    assert "не отправляет" in auto_sync

    sessions = (repo_root / "cold" / "memory" / "sessions_policy.md").read_text(
        encoding="utf-8"
    )
    assert "локально" in sessions
    assert "не отправляются" in sessions

    mcp = (repo_root / "cold" / "memory" / "reference_mcp.md").read_text(
        encoding="utf-8"
    )
    assert "lazy" in mcp.lower()
    assert "BLOCKED" in mcp


def test_entire_installable_payload_has_no_legacy_runtime_contract(repo_root):
    """Catches legacy runtime coupling hidden below a native SKILL.md entrypoint."""
    roots = [repo_root / "agents", repo_root / "skills", repo_root / "cold"]
    text_suffixes = {
        ".md",
        ".txt",
        ".py",
        ".ps1",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".patch",
        ".lsp",
        ".tmpl",
    }
    forbidden = (
        r"(?i)(?:^|[/\\])\.claude(?:[/\\]|$)",
        r"(?:^|[/\\])\.Codex(?:[/\\]|$)",
        r"\bCLAUDE\.md\b",
        r"\bAskUserQuestion\b",
        r"\bTaskCreate\b",
        r"\bTaskUpdate\b",
        r"\bTodoWrite\b",
        r"\bWorkflow\s*\(",
        r"\bmcp__",
        r"\bCLAUDE_[A-Z_]+\b",
        r"claude_desktop_config\.json",
        r"superpowers:brainstorming",
        r"docs/superpowers",
        r"(?i)~[/\\]\.codex[/\\]base[/\\](?:agents|skills)(?:[/\\]|$)",
        r"(?i)\b(?:auto-push|pull-feedback|feedback-pending)\b",
        r"(?i)\b(?:sonnet|opus|haiku|kimi)\b",
    )

    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in text_suffixes:
                continue
            assert "tests" not in path.parts
            assert "__pycache__" not in path.parts
            text = path.read_text(encoding="utf-8")
            for pattern in forbidden:
                assert not re.search(pattern, text), f"{pattern} leaked into {path}"
            if "llm-interop" not in path.parts:
                assert not re.search(
                    r"\bClaude\b", text, re.IGNORECASE
                ), f"provider term leaked outside interop content: {path}"


def test_python_payload_is_syntactically_valid(repo_root):
    """Catches unsafe mechanical vocabulary rewrites inside executable helpers."""
    for path in (repo_root / "skills").rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert not path.name.startswith("test_")


def test_project_memory_bootstrap_is_native_idempotent_and_hook_free(
    repo_root, tmp_path
):
    script = repo_root / "skills" / "project-memory" / "tools" / "bootstrap.py"
    first = subprocess.run(
        [
            sys.executable,
            str(script),
            "Тестовый проект",
            "--target",
            str(tmp_path),
            "--role",
            "инженер",
            "--domain",
            "ОВ",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert first.returncode == 0, first.stderr

    expected = {
        Path("AGENTS.md"),
        Path("Codex/AGENTS.md"),
        Path("Codex/README.md"),
        Path("Codex/STATUS.md"),
        Path("Codex/КОНТЕКСТ.md"),
        Path("Codex/ЖУРНАЛ СЕССИЙ.md"),
    }
    assert expected <= {
        path.relative_to(tmp_path)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    context = (tmp_path / "Codex" / "КОНТЕКСТ.md").read_text(encoding="utf-8")
    assert "designer" in context

    root_agents = tmp_path / "AGENTS.md"
    root_agents.write_text("# Personal project rule\n", encoding="utf-8")
    second = subprocess.run(
        [sys.executable, str(script), "Тестовый проект", "--target", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert second.returncode == 0, second.stderr
    assert root_agents.read_text(encoding="utf-8") == "# Personal project rule\n"

    project_memory = repo_root / "skills" / "project-memory"
    assert not (project_memory / "tools" / "hooks").exists()
    assert not (project_memory / "tools" / "gen_project_agents.py").exists()


def test_skill_local_file_references_are_closed(repo_root):
    """Catches instructions that name a script/template/reference omitted from ZIP."""
    reference_pattern = re.compile(
        r"`((?:tools|references|templates|assets|examples|prompts)/"
        r"[^`\s,;:)]+)"
    )
    for skill in sorted((repo_root / "skills").iterdir()):
        entrypoint = skill / "SKILL.md"
        if not entrypoint.is_file():
            continue
        text = entrypoint.read_text(encoding="utf-8")
        for value in reference_pattern.findall(text):
            if any(marker in value for marker in ("<", ">", "*", "{", "}")):
                continue
            path = skill / value.rstrip("./")
            assert path.exists(), f"missing local dependency {value} in {skill.name}"


def test_bundled_document_templates_are_valid_docx_packages(repo_root):
    templates = (
        repo_root
        / "skills"
        / "stroy-formatting"
        / "assets"
        / "templates"
    )
    expected = {
        "gost-report-full.docx",
        "gost-report-light.docx",
        "gost-report-with-border.docx",
        "plain-clean.docx",
    }
    assert {path.name for path in templates.glob("*.docx")} == expected
    for path in templates.glob("*.docx"):
        with zipfile.ZipFile(path) as package:
            assert "[Content_Types].xml" in package.namelist()
            assert "word/document.xml" in package.namelist()


def test_powershell_payload_parses_in_ps7_and_windows_powershell_51(repo_root):
    checker = repo_root / "tools" / "check_ps_syntax.ps1"
    executables = [
        value
        for value in (shutil.which("pwsh"), shutil.which("powershell.exe"))
        if value
    ]
    assert executables
    for executable in executables:
        result = subprocess.run(
            [
                executable,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(checker),
                "-Root",
                str(repo_root / "skills"),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr


def test_worst_case_windows_install_paths_stay_below_legacy_limit(repo_root):
    prefix = Path(
        r"C:\Users\Employee With A Very Long Windows Profile Name"
    )
    mappings = (
        (repo_root / "agents", Path(".codex/agents")),
        (repo_root / "skills", Path(".agents/skills")),
        (repo_root / "control-skills", Path(".agents/skills")),
        (repo_root / "cold", Path(".codex/base/cold")),
        (repo_root / "runtime" / "hooks", Path(".codex/base/runtime/hooks")),
    )
    installed = []
    for source, destination in mappings:
        for path in source.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                installed.append(prefix / destination / path.relative_to(source))

    assert installed
    assert max(len(str(path)) for path in installed) < 240


def test_llm_interop_documentation_matches_bridge_cli(repo_root):
    skill = (
        repo_root / "skills" / "llm-interop" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "--task .llm-interop/task.json" in skill
    assert "references/task.schema.json" in skill
    assert "--custom agent" not in skill
    assert "custom agent.schema.json" not in skill
