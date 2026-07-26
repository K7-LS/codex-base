from __future__ import annotations

import json
import re
import shutil
from pathlib import Path


_TEXT_SUFFIXES = {
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
_PROSE_SUFFIXES = {".md", ".txt", ".patch", ".tmpl"}

_MCP_CAPABILITIES = {
    "word": "document.word.read",
    "excel": "spreadsheet.read",
    "pdf-mcp": "pdf.read",
    "fetch": "web.fetch",
    "exa": "web.search",
    "firecrawl": "web.fetch",
    "playwright": "web.browser.interact",
    "autocad-mcp": "cad.read",
    "revit-connector": "revit.inspect",
    "mineru": "pdf.read",
    "time": "time.read",
    "markitdown": "document.read",
    "document-loader": "document.read",
}


def _split_frontmatter(text: str) -> tuple[str, str]:
    normalized = text.replace("\r\n", "\n")
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", normalized, re.DOTALL)
    if not match:
        raise ValueError("missing YAML frontmatter")
    return match.group(1), match.group(2)


def _frontmatter_value(frontmatter: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:[ \t]*(.*)$", frontmatter, re.MULTILINE)
    if not match:
        return ""
    first = match.group(1).strip()
    if first not in {"|", "|-", ">", ">-"}:
        return first.strip("\"'")
    values: list[str] = []
    for line in frontmatter[match.end() :].splitlines():
        if not line.strip():
            values.append("")
        elif line.startswith((" ", "\t")):
            values.append(line.strip())
        else:
            break
    return ("\n" if first.startswith("|") else " ").join(values).strip()


def _replace_mcp_tool(match: re.Match[str]) -> str:
    server = match.group(1).lower()
    capability = _MCP_CAPABILITIES.get(server, "external.tool")
    return f"capability `{capability}`"


def _native_path_text(text: str) -> str:
    replacements = (
        (r"~[/\\]\.Codex[/\\]skills[/\\]", "~/.agents/skills/"),
        (r"~[/\\]\.Codex[/\\]agents[/\\]", "~/.codex/agents/"),
        (r"~[/\\]\.Codex[/\\]memory[/\\]", "~/.codex/base/cold/memory/"),
        (r"~[/\\]\.Codex[/\\]AGENTS\.md\b", "~/.codex/AGENTS.md"),
        (r"~[/\\]\.claude[/\\]skills[/\\]", "~/.agents/skills/"),
        (r"~[/\\]\.claude[/\\]memory[/\\]", "~/.codex/base/cold/memory/"),
        (r"~[/\\]\.claude[/\\]", "~/.codex/base/"),
        (r"\.claude[/\\]skills[/\\]", ".agents/skills/"),
        (r"\.claude[/\\]memory[/\\]", ".codex/base/cold/memory/"),
        (r"\.claude[/\\]", ".codex/base/"),
        (
            r"~[/\\]\.codex[/\\]base[/\\]agents[/\\]",
            "~/.codex/agents/",
        ),
        (
            r"~[/\\]\.codex[/\\]base[/\\]skills[/\\]",
            "~/.agents/skills/",
        ),
        (
            r"~[/\\]\.codex[/\\]base[/\\]AGENTS\.md\b",
            "~/.codex/AGENTS.md",
        ),
        (r"\bCLAUDE\.md\b", "AGENTS.md"),
        (r"\bClaude[/\\]", "Codex/"),
        (r"\.claude\b", ".codex"),
        (r"\.Codex\b", ".codex"),
    )
    result = text
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def _native_runtime_text(text: str, *, allow_interop: bool = False) -> str:
    replacements = (
        (r"\bAskUserQuestion\b", "request_user_input"),
        (r"\bTodoWrite\b", "task plan"),
        (r"\bTaskCreate\b", "task plan"),
        (r"\bTaskUpdate\b", "task plan"),
        (r"\bWorkflow\b", "native task plan"),
        (r"\bTask\b", "custom agent"),
        (r"\*\*Read\*\*", "**capability `core.files.read`**"),
        (r"\*\*Write/Edit\*\*", "**capability `core.files.write`**"),
        (r"\*\*Bash\*\*", "**capability `core.shell.execute`**"),
        (r"`Read`", "`core.files.read`"),
        (r"`Glob`", "`core.search.files`"),
        (r"`Grep`", "`core.search.text`"),
        (r"`Bash`", "`core.shell.execute`"),
        (r"`WebFetch`", "`web.fetch`"),
        (r"`WebSearch`", "`web.search`"),
        (r"\bRead\(", "core.files.read("),
        (r"\bGlob\(", "core.search.files("),
        (r"\bGrep\(", "core.search.text("),
        (
            r"docs[/\\]superpowers[/\\](?:specs|plans)[/\\][^\s`,)]+",
            "the native Plan Mode record",
        ),
        (r"основному Claude", "основному Codex"),
        (r"основной Claude", "основной Codex"),
    )
    result = _native_path_text(text)
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    result = re.sub(
        r"mcp__([A-Za-z0-9-]+)(?:__[A-Za-z0-9_*\\-]+)?",
        _replace_mcp_tool,
        result,
        flags=re.IGNORECASE,
    )
    if not allow_interop:
        result = re.sub(r"\bClaude Code\b", "Codex", result, flags=re.IGNORECASE)
        result = re.sub(
            r"\bClaude Desktop\b", "Codex desktop", result, flags=re.IGNORECASE
        )
        result = re.sub(r"\bClaude\b", "Codex", result, flags=re.IGNORECASE)
        result = re.sub(
            r"\b(?:sonnet|opus|haiku|kimi)\b",
            "selected model",
            result,
            flags=re.IGNORECASE,
        )
    return result


def _native_support_text(text: str, *, allow_interop: bool = False) -> str:
    """Convert paths and explicit tool identifiers without rewriting code symbols."""
    result = _native_path_text(text)
    for pattern, replacement in (
        (r"\bAskUserQuestion\b", "request_user_input"),
        (r"\bTodoWrite\b", "update_plan"),
        (r"\bTaskCreate\b", "update_plan"),
        (r"\bTaskUpdate\b", "update_plan"),
    ):
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    result = re.sub(
        r"mcp__([A-Za-z0-9-]+)(?:__[A-Za-z0-9_*\\-]+)?",
        _replace_mcp_tool,
        result,
        flags=re.IGNORECASE,
    )
    if not allow_interop:
        result = re.sub(r"\bClaude Code\b", "Codex", result, flags=re.IGNORECASE)
        result = re.sub(
            r"\bClaude Desktop\b", "Codex desktop", result, flags=re.IGNORECASE
        )
        result = re.sub(r"\bClaude\b", "Codex", result, flags=re.IGNORECASE)
        result = re.sub(
            r"\b(?:sonnet|opus|haiku|kimi)\b",
            "selected-model",
            result,
            flags=re.IGNORECASE,
        )
    return result


def _copy_skill_tree(source_root: Path, destination_root: Path) -> None:
    if destination_root.exists():
        shutil.rmtree(destination_root)
    shutil.copytree(
        source_root,
        destination_root,
        copy_function=shutil.copy2,
        ignore=shutil.ignore_patterns(
            "tests",
            "__pycache__",
            ".pytest_cache",
            "test_*.py",
            "*.pyc",
            "*.pyo",
        ),
    )


def _rename_native_files(root: Path) -> None:
    candidates = sorted(
        (
            path
            for path in root.rglob("*")
            if "CLAUDE" in path.name.upper()
        ),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in candidates:
        replacement = re.sub("CLAUDE", "AGENTS", path.name, flags=re.IGNORECASE)
        path.rename(path.with_name(replacement))


def _transform_skill_tree(root: Path, *, allow_interop: bool) -> None:
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        transformer = (
            _native_runtime_text
            if path.suffix.lower() in _PROSE_SUFFIXES
            else _native_support_text
        )
        path.write_text(
            transformer(source, allow_interop=allow_interop),
            encoding="utf-8",
            newline="\n",
        )
    _rename_native_files(root)


def _apply_skill_prune(destination_root: Path, override_root: Path) -> None:
    manifest = override_root / ".remove.json"
    if not manifest.is_file():
        return
    values = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise ValueError(f"skill prune manifest must be a list: {manifest}")
    destination_resolved = destination_root.resolve()
    for value in values:
        relative = _relative_path(value)
        target = (destination_root / relative).resolve()
        try:
            target.relative_to(destination_resolved)
        except ValueError as exc:
            raise ValueError(f"unsafe skill prune target: {value}") from exc
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def convert_agent_source(source: str, metadata: dict[str, object]) -> str:
    _, body = _split_frontmatter(source)
    instructions = _native_runtime_text(body).strip()
    required = ", ".join(str(item) for item in metadata["required_capabilities"])
    instructions += (
        "\n\nCapability contract:\n"
        f"- required: {required or 'none'}\n"
        f"- permission_class: {metadata['permission_class']}\n"
        "- unavailable capability: return BLOCKED with the missing capability name"
    )
    rows = [
        f"name = {json.dumps(str(metadata['name']), ensure_ascii=False)}",
        f"description = {json.dumps(str(metadata['description']), ensure_ascii=False)}",
    ]
    if metadata["permission_class"] == "ro":
        rows.append('sandbox_mode = "read-only"')
    rows.append(
        "developer_instructions = "
        + json.dumps(instructions, ensure_ascii=False)
    )
    return "\n".join(rows) + "\n"


def convert_skill_source(source: str, metadata: dict[str, object]) -> str:
    _, body = _split_frontmatter(source)
    native_body = _native_runtime_text(
        body,
        allow_interop=str(metadata.get("id")) == "llm-interop",
    ).strip()
    return (
        "---\n"
        f"name: {metadata['name']}\n"
        f"description: {metadata['description']}\n"
        "---\n\n"
        f"{native_body}\n"
    )


def _relative_path(value: object) -> Path:
    path = Path(str(value))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe relative path: {value}")
    return path


def materialize_legacy(
    legacy_root: Path,
    target_root: Path,
    catalog: dict[str, list[dict[str, object]]],
    cold_catalog: dict[str, list[str]],
) -> None:
    for item in catalog["agents"]:
        legacy_name = str(item.get("legacy_source") or item["name"])
        source = legacy_root / "agents" / f"{legacy_name}.md"
        destination = target_root / _relative_path(item["source"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            convert_agent_source(source.read_text(encoding="utf-8"), item),
            encoding="utf-8",
            newline="\n",
        )

    for item in catalog["skills"]:
        source_root = legacy_root / "skills" / str(item["id"])
        destination_entrypoint = target_root / _relative_path(item["source"])
        _copy_skill_tree(source_root, destination_entrypoint.parent)
        override_root = (
            target_root / "native-overrides" / "skills" / str(item["id"])
        )
        if override_root.is_dir():
            _apply_skill_prune(destination_entrypoint.parent, override_root)
            shutil.copytree(
                override_root,
                destination_entrypoint.parent,
                dirs_exist_ok=True,
                copy_function=shutil.copy2,
                ignore=shutil.ignore_patterns(".remove.json"),
            )
        _transform_skill_tree(
            destination_entrypoint.parent,
            allow_interop=str(item["id"]) == "llm-interop",
        )
        destination_entrypoint.write_text(
            convert_skill_source(
                (
                    override_root / "SKILL.md"
                    if (override_root / "SKILL.md").is_file()
                    else source_root / "SKILL.md"
                ).read_text(encoding="utf-8"),
                item,
            ),
            encoding="utf-8",
            newline="\n",
        )

    for group in ("memory", "chains", "commands"):
        for value in cold_catalog[group]:
            relative = _relative_path(value)
            source = legacy_root / relative
            destination = target_root / "cold" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            override = target_root / "native-overrides" / "cold" / relative
            selected = override if override.is_file() else source
            destination.write_text(
                _native_runtime_text(selected.read_text(encoding="utf-8")),
                encoding="utf-8",
                newline="\n",
            )
