"""Fail-closed policy helper for Codex lifecycle hooks."""

from __future__ import annotations

import re
import shlex


SAFE_TOOLS = {
    "update_plan",
    "view_image",
    "read_mcp_resource",
}
WRITE_TOOLS = {"apply_patch", "Edit", "Write"}

SENSITIVE_WRITE = re.compile(
    r"(\.codex[/\\](?:config\.toml|hooks\.json|agents[/\\]))"
    r"|(\.git[/\\]hooks)|(\.ssh[/\\])"
    r"|(\.bashrc|\.zshrc|\.profile|profile\.ps1)"
    r"|(start ?menu[/\\]programs[/\\]startup)|(\bautostart\b)",
    re.I,
)

DENY_SUBSTR = [
    "rm -rf",
    "rm -fr",
    "mkfs",
    "dd if=",
    ":(){",
    "> /dev/sda",
    "format-volume",
    "clear-disk",
    "vssadmin delete",
    "invoke-expression",
]
DENY_TOKENS = [
    ("git", "push", "--force"),
    ("git", "push", "-f"),
    ("git", "reset", "--hard"),
    ("drop", "database"),
    ("drop", "table"),
    ("rm", "-r", "-f"),
    ("rm", "-f", "-r"),
    ("chmod", "777"),
    ("chmod", "-r", "777"),
    ("remove-item", "-recurse", "-force"),
    ("rd", "/s"),
    ("rmdir", "/s"),
    ("del", "/s"),
    ("reg", "delete"),
]
WRAPPERS = {
    "bash",
    "sh",
    "zsh",
    "python",
    "python3",
    "node",
    "perl",
    "ruby",
    "eval",
    "powershell",
    "pwsh",
    "cmd",
}
WRAPPER_FLAGS = {
    "-c",
    "-e",
    "-ce",
    "-command",
    "-encodedcommand",
    "-enc",
    "-ec",
    "-file",
    "/c",
    "/k",
}
PIPE_TARGETS = WRAPPERS | {"iex"}


def _analyze_shell(command: str) -> tuple[str, str]:
    lowered = command.lower()
    for value in DENY_SUBSTR:
        if value in lowered:
            return "escalate", f"dangerous substring «{value}»"
    try:
        tokens = [token.lower() for token in shlex.split(command)]
    except ValueError:
        return "escalate", "unparseable command"
    if tokens and tokens[0] in WRAPPERS:
        hidden = next(
            (token for token in tokens[1:] if token in WRAPPER_FLAGS),
            None,
        )
        if hidden:
            return "escalate", f"wrapper hides command ({tokens[0]} {hidden})"
    if "|" in command:
        for segment in command.split("|")[1:]:
            first = segment.strip().split()
            if first and first[0].lower().strip("\"'") in PIPE_TARGETS:
                target = first[0].strip("\"'").lower()
                return "escalate", f"pipe into interpreter ({target})"
    for combination in DENY_TOKENS:
        if all(token in tokens for token in combination):
            return "escalate", "dangerous tokens «" + " ".join(combination) + "»"
    return "allow", ""


def decide(tool_name: str, tool_input: dict) -> dict:
    if tool_name in SAFE_TOOLS:
        return {"action": "allow", "reason": "read-only/local planning tool"}
    if tool_name in WRITE_TOOLS:
        target = str(
            tool_input.get("file_path")
            or tool_input.get("path")
            or tool_input.get("patch")
            or tool_input.get("input")
            or ""
        )
        if SENSITIVE_WRITE.search(target):
            return {
                "action": "escalate",
                "reason": f"write to sensitive Codex surface: {target[:120]}",
            }
        return {"action": "allow", "reason": "workspace file write"}
    if tool_name == "Bash":
        action, detail = _analyze_shell(str(tool_input.get("command", "")))
        return {
            "action": action,
            "reason": f"shell: {detail}" if detail else "shell: allow",
        }
    return {"action": "escalate", "reason": "unknown Codex tool — no rule"}
