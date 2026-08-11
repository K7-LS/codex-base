#!/usr/bin/env python3
"""Общее обнаружение переносимого ядра проекта для Claude и Codex."""

from pathlib import Path

JOURNAL_NAME = "ЖУРНАЛ СЕССИЙ.md"
CORE_RULES = {
    "Claude": "CLAUDE.md",
    "Codex": "AGENTS.md",
}


class CoreConflict(RuntimeError):
    """В проекте найдено несколько ядер без единого выбранного канона."""


def is_valid_core(root: Path, core_name: str) -> bool:
    """Ядро считается развёрнутым только по трём устойчивым маркерам."""
    core = Path(root) / core_name
    return all(
        (core / name).is_file()
        for name in (CORE_RULES[core_name], "STATUS.md", JOURNAL_NAME)
    )


def _entrypoint_choice(root: Path, candidates: list[str]) -> set[str]:
    choices: set[str] = set()
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = Path(root) / name
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        normalized = text.replace("\\", "/")
        for candidate in candidates:
            if f"{candidate}/" in normalized:
                choices.add(candidate)
    return choices


def select_core(root: Path) -> str | None:
    """Возвращает единственное активное ядро или None, если ядра ещё нет."""
    root = Path(root)
    candidates = [name for name in CORE_RULES if is_valid_core(root, name)]
    if len(candidates) <= 1:
        return candidates[0] if candidates else None

    choices = _entrypoint_choice(root, candidates)
    if len(choices) == 1:
        return next(iter(choices))
    found = ", ".join(f"{name}/" for name in candidates)
    raise CoreConflict(
        f"CORE_CONFLICT: найдены несколько ядер ({found}). "
        "Укажите один канон в корневых AGENTS.md и CLAUDE.md; "
        "автоматическое объединение и перезапись запрещены."
    )


def find_project_core(start: Path, max_levels: int = 12) -> tuple[Path, str] | None:
    """Идёт вверх от пути и возвращает (корень проекта, имя активного ядра)."""
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    for _ in range(max_levels):
        root = current.parent if current.name in CORE_RULES else current
        selected = select_core(root)
        if selected:
            return root, selected
        if current.parent == current:
            break
        current = current.parent
    return None
