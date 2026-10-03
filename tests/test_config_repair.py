"""Regression cases for the warnings seen on two employee devices."""

import importlib.util
from pathlib import Path
import tomllib


SCRIPT = Path(__file__).parents[1] / "runtime" / "maintenance" / "repair_codex_config.py"
SPEC = importlib.util.spec_from_file_location("repair_codex_config", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_known_config_warnings_are_repaired_with_backup(tmp_path: Path) -> None:
    codex = tmp_path / ".codex"
    codex.mkdir()
    config = codex / "config.toml"
    original = (
        'model = "user-choice"\n'
        '[computer_use.windows.always_allowed_app_ids]\n'
        '"explorer.exe" = true\n'
        '[features.guardianv2]\n'
        'thread_context = true\n'
        'other_setting = true\n'
        '[profiles.employee.features.guardianv2]\n'
        'thread_context = false\n'
    )
    config.write_text(original, encoding="utf-8")
    report = MODULE.inspect(tmp_path, apply=True)
    assert len(report["warnings"]) == 2
    assert (Path(report["backup"]) / ".codex" / "config.toml").read_text("utf-8") == original
    repaired = tomllib.loads(config.read_text("utf-8"))
    assert repaired["model"] == "user-choice"
    assert repaired["features"]["guardianv2"]["other_setting"] is True
    assert "thread_context" not in repaired["features"]["guardianv2"]
    assert "computer_use" not in repaired


def test_hindsight_moves_only_with_verified_project_bridge(tmp_path: Path) -> None:
    codex = tmp_path / ".codex"
    codex.mkdir()
    config = codex / "config.toml"
    config.write_text(
        '[hooks.state]\nkey = "keep"\n'
        + "".join(
            f'[[hooks.{event}]]\n[[hooks.{event}.hooks]]\n'
            f'type = "command"\ncommand = "node C:/.hindsight/{filename}"\n'
            for event, filename in MODULE.HINDSIGHT_EVENTS.items()
        ), encoding="utf-8",
    )
    (codex / "hooks.json").write_text('{"hooks":{}}', encoding="utf-8")
    project = tmp_path / "project"
    (project / ".codex" / "hooks").mkdir(parents=True)
    (project / ".codex" / "hooks.json").write_text("{}", encoding="utf-8")
    (project / ".codex" / "hooks" / "hindsight-bridge.ps1").write_text("", encoding="utf-8")
    report = MODULE.inspect(tmp_path, project, apply=True)
    assert not report["needs_review"]
    assert tomllib.loads(config.read_text("utf-8"))["hooks"] == {"state": {"key": "keep"}}


def test_different_duplicate_agents_require_review(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    (agents / "smetchik.toml").write_text('name = "сметчик"\ndescription = "new"\n', encoding="utf-8")
    (agents / "legacy.toml").write_text('name = "сметчик"\ndescription = "old"\n', encoding="utf-8")
    report = MODULE.inspect(tmp_path, apply=True)
    assert any("duplicate agent role" in item for item in report["warnings"])
    assert any("no automatic deletion" in item for item in report["needs_review"])
    assert sorted(path.name for path in agents.iterdir()) == ["legacy.toml", "smetchik.toml"]
