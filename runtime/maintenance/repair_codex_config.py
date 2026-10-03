"""Diagnose and repair narrowly identified Codex config warnings.

Run without --apply to inspect. This tool never reads auth or sessions and
backs up every file it changes under the selected home.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import tomllib
from datetime import datetime, timezone


INVALID_TABLE = "[computer_use.windows.always_allowed_app_ids]"
HINDSIGHT_EVENTS = {
    "SessionStart": "codex-sessionstart-hook.js",
    "UserPromptSubmit": "codex-hook.js",
    "Stop": "codex-stop-hook.js",
}


def _remove_table(raw: str, header: str) -> str:
    lines = raw.splitlines(keepends=True)
    result: list[str] = []
    skip = False
    for line in lines:
        stripped = line.strip()
        if stripped == header:
            skip = True
            continue
        if skip and stripped.startswith("["):
            skip = False
        if not skip:
            result.append(line)
    return "".join(result)


def _remove_guardian_setting(raw: str) -> str:
    lines = raw.splitlines(keepends=True)
    result: list[str] = []
    in_guardian = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_guardian = bool(re.match(
                r"^\[(?:profiles\.[^.]+\.)?features\.guardianv2\]$", stripped
            ))
        if in_guardian and re.match(r"^thread_context\s*=", stripped):
            continue
        result.append(line)
    return "".join(result)


def _only_expected_hindsight_hooks(config: dict) -> bool:
    hooks = config.get("hooks")
    if not isinstance(hooks, dict) or set(hooks) - {"state"} != set(HINDSIGHT_EVENTS):
        return False
    for event, filename in HINDSIGHT_EVENTS.items():
        groups = hooks[event]
        if not isinstance(groups, list) or len(groups) != 1:
            return False
        if set(groups[0]) != {"hooks"}:
            return False
        handlers = groups[0].get("hooks")
        if not isinstance(handlers, list) or len(handlers) != 1:
            return False
        handler = handlers[0]
        if set(handler) != {"type", "command", "timeout"} or handler["type"] != "command":
            return False
        if handler["timeout"] != (60 if event == "Stop" else 30):
            return False
        command = handler["command"]
        expected = rf'^node\s+"?[^"\n]*[\\/]\.hindsight[\\/]coding-agents[\\/]dist[\\/]{re.escape(filename)}"?$'
        if not isinstance(command, str) or not re.fullmatch(expected, command, re.IGNORECASE):
            return False
    return True


def _remove_inline_hook_arrays(raw: str) -> str:
    """Remove the known inline hook arrays without touching later TOML tables."""
    result: list[str] = []
    in_hook_array = False
    for line in raw.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[[hooks.") and stripped.endswith("]]"):
            in_hook_array = True
        elif stripped.startswith("[") and stripped.endswith("]"):
            in_hook_array = False
        if not in_hook_array:
            result.append(line)
    return "".join(result)


def _verified_project_bridge(home: Path, project: Path | None) -> bool:
    if project is None:
        return False
    asset_root = home / ".agents" / "skills" / "llm-interop" / "assets" / "hindsight-project-hooks"
    project_root = project / ".codex"
    for relative in (Path("hooks.json"), Path("hooks/hindsight-bridge.ps1")):
        reference = asset_root / relative
        installed = project_root / relative
        if not reference.is_file() or not installed.is_file() or reference.read_bytes() != installed.read_bytes():
            return False
    hindsight = home / ".hindsight"
    if not (hindsight / "coding-agent.json").is_file():
        return False
    return all((hindsight / "coding-agents" / "dist" / name).is_file() for name in HINDSIGHT_EVENTS.values())


def inspect(home: Path, project: Path | None = None, apply: bool = False,
            verified_project_bridge: bool = False) -> dict:
    home = home.resolve()
    config_path = home / ".codex" / "config.toml"
    hooks_path = home / ".codex" / "hooks.json"
    agents_dir = home / ".codex" / "agents"
    report: dict = {"home": str(home), "warnings": [], "repaired": [], "needs_review": []}
    changes: dict[Path, bytes] = {}
    moves: list[Path] = []

    if config_path.is_file():
        original = config_path.read_bytes()
        raw = original.decode("utf-8-sig")
        parsed = tomllib.loads(raw)
        updated = raw
        if INVALID_TABLE in raw:
            report["warnings"].append("ignored computer_use.windows.always_allowed_app_ids")
            updated = _remove_table(updated, INVALID_TABLE)
        if _remove_guardian_setting(updated) != updated:
            report["warnings"].append("deprecated features.guardianv2.thread_context")
            updated = _remove_guardian_setting(updated)
        if hooks_path.is_file() and set(parsed.get("hooks", {})) - {"state"}:
            report["warnings"].append("hooks.json and inline hooks in the same user layer")
            if (verified_project_bridge and _verified_project_bridge(home, project)
                    and _only_expected_hindsight_hooks(parsed)):
                updated = _remove_inline_hook_arrays(updated)
            else:
                report["needs_review"].append(
                    "inline hooks retained: verify the project hook in Codex, then use "
                    "--verified-project-bridge with an unchanged bridge template"
                )
        if updated != raw:
            # Preserve the original line-ending style and UTF-8 BOM, if any.
            if "\r\n" in raw:
                updated = updated.replace("\r\n", "\n").replace("\n", "\r\n")
            encoded = (b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b"") + updated.encode("utf-8")
            tomllib.loads(updated)
            changes[config_path] = encoded

    if agents_dir.is_dir():
        desired_path = home / ".codex" / "base" / "desired-state.json"
        managed_ids: set[str] = set()
        if desired_path.is_file():
            try:
                desired = json.loads(desired_path.read_text(encoding="utf-8"))
                managed_ids = set(desired.get("agents", []))
            except (OSError, ValueError, TypeError):
                report["needs_review"].append("managed agent inventory is unreadable")
        by_name: dict[str, list[Path]] = {}
        for path in sorted(agents_dir.glob("*.toml")):
            try:
                name = tomllib.loads(path.read_text(encoding="utf-8-sig")).get("name")
            except (UnicodeError, tomllib.TOMLDecodeError):
                report["needs_review"].append(f"invalid agent TOML: {path.name}")
                continue
            if isinstance(name, str) and name:
                by_name.setdefault(name.casefold(), []).append(path)
        for name, paths in by_name.items():
            if len(paths) < 2:
                continue
            report["warnings"].append(f"duplicate agent role {name}: {', '.join(p.name for p in paths)}")
            ordered = sorted(paths, key=lambda path: (path.stem not in managed_ids, path.name))
            reference = ordered[0].read_bytes()
            if all(path.read_bytes() == reference for path in ordered[1:]):
                moves.extend(ordered[1:])
            else:
                report["needs_review"].append(f"different definitions for role {name}; no automatic deletion")

    if apply and (changes or moves):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = home / ".codex-backups" / f"config-repair-{stamp}"
        if backup.exists():
            raise FileExistsError(backup)
        backup.mkdir(parents=True)
        affected = [*changes, *moves]
        for path in affected:
            relative = path.relative_to(home)
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        try:
            for path, payload in changes.items():
                path.write_bytes(payload)
                report["repaired"].append(str(path.relative_to(home)))
            for path in moves:
                path.unlink()
                report["repaired"].append(str(path.relative_to(home)))
        except OSError:
            for path in affected:
                shutil.copy2(backup / path.relative_to(home), path)
            raise
        report["backup"] = str(backup)
    else:
        report["proposed_changes"] = [str(path.relative_to(home)) for path in (*changes, *moves)]
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verified-project-bridge", action="store_true",
                        help="Assert that Codex has activated the project Hindsight hook")
    args = parser.parse_args()
    print(json.dumps(inspect(args.home, args.project, args.apply,
                             args.verified_project_bridge), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
