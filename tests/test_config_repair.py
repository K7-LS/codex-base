"""Regression cases for the warnings seen on two employee devices."""

import importlib.util
from pathlib import Path
import shutil
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
            f'type = "command"\ncommand = "node C:/.hindsight/coding-agents/dist/{filename}"\n'
            f'timeout = {60 if event == "Stop" else 30}\n'
            for event, filename in MODULE.HINDSIGHT_EVENTS.items()
        ) + '[mcp_servers.keep]\nurl = "https://example.test/mcp"\n'
        + '[profiles.employee]\nmodel = "user-choice"\n', encoding="utf-8",
    )
    (codex / "hooks.json").write_text('{"hooks":{}}', encoding="utf-8")
    project = tmp_path / "project"
    (project / ".codex" / "hooks").mkdir(parents=True)
    assets = SCRIPT.parents[2] / "skills" / "llm-interop" / "assets" / "hindsight-project-hooks"
    installed_assets = tmp_path / ".agents" / "skills" / "llm-interop" / "assets" / "hindsight-project-hooks"
    shutil.copytree(assets, installed_assets)
    shutil.copy2(assets / "hooks.json", project / ".codex" / "hooks.json")
    shutil.copy2(assets / "hooks" / "hindsight-bridge.ps1", project / ".codex" / "hooks" / "hindsight-bridge.ps1")
    hindsight = tmp_path / ".hindsight"
    scripts = hindsight / "coding-agents" / "dist"
    scripts.mkdir(parents=True)
    (hindsight / "coding-agent.json").write_text("{}", encoding="utf-8")
    for filename in MODULE.HINDSIGHT_EVENTS.values():
        (scripts / filename).write_text("// test script", encoding="utf-8")
    before_verification = MODULE.inspect(tmp_path, project, apply=False)
    assert before_verification["needs_review"]
    assert ".codex/config.toml" not in before_verification["proposed_changes"]
    report = MODULE.inspect(tmp_path, project, apply=True, verified_project_bridge=True)
    assert not report["needs_review"]
    repaired = tomllib.loads(config.read_text("utf-8"))
    assert repaired["hooks"] == {"state": {"key": "keep"}}
    assert repaired["mcp_servers"]["keep"]["url"] == "https://example.test/mcp"
    assert repaired["profiles"]["employee"]["model"] == "user-choice"


def test_empty_project_bridge_does_not_remove_hindsight_hooks(tmp_path: Path) -> None:
    codex = tmp_path / ".codex"
    codex.mkdir()
    config = codex / "config.toml"
    config.write_text('[hooks.state]\nkey = "keep"\n[[hooks.Stop]]\n[[hooks.Stop.hooks]]\n'
                      'type = "command"\ncommand = "node C:/.hindsight/coding-agents/dist/codex-stop-hook.js"\n'
                      'timeout = 60\n', encoding="utf-8")
    (codex / "hooks.json").write_text('{"hooks":{}}', encoding="utf-8")
    project = tmp_path / "project"
    (project / ".codex" / "hooks").mkdir(parents=True)
    (project / ".codex" / "hooks.json").write_text("{}", encoding="utf-8")
    (project / ".codex" / "hooks" / "hindsight-bridge.ps1").write_text("", encoding="utf-8")
    report = MODULE.inspect(tmp_path, project, apply=True, verified_project_bridge=True)
    assert report["needs_review"]
    assert "[[hooks.Stop]]" in config.read_text("utf-8")


def test_different_duplicate_agents_require_review(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    (agents / "smetchik.toml").write_text('name = "сметчик"\ndescription = "new"\n', encoding="utf-8")
    (agents / "legacy.toml").write_text('name = "сметчик"\ndescription = "old"\n', encoding="utf-8")
    report = MODULE.inspect(tmp_path, apply=True)
    assert any("duplicate agent role" in item for item in report["warnings"])
    assert any("no automatic deletion" in item for item in report["needs_review"])
    assert sorted(path.name for path in agents.iterdir()) == ["legacy.toml", "smetchik.toml"]


def test_identical_duplicate_keeps_managed_filename(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    payload = 'name = "сметчик"\ndescription = "same"\n'
    (agents / "legacy.toml").write_text(payload, encoding="utf-8")
    (agents / "smetchik.toml").write_text(payload, encoding="utf-8")
    base = tmp_path / ".codex" / "base"
    base.mkdir()
    (base / "desired-state.json").write_text('{"agents":["smetchik"]}', encoding="utf-8")
    report = MODULE.inspect(tmp_path, apply=True)
    assert [path.name for path in agents.iterdir()] == ["smetchik.toml"]
    assert (Path(report["backup"]) / ".codex" / "agents" / "legacy.toml").is_file()
