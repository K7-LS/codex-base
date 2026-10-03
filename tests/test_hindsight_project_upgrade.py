"""Exercise bridge migration without using real settings, auth or memory."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hindsight_upgrade", ROOT / "runtime/maintenance/upgrade_hindsight_project.py"
)
UPGRADE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPGRADE)


@pytest.fixture
def installation(tmp_path):
    home, project = tmp_path / "home", tmp_path / "Проект с пробелами"
    templates = home / ".agents/skills/llm-interop/assets/hindsight-project-hooks"
    for name in UPGRADE.FILES:
        for destination, source in (
            (templates, ROOT / "skills/llm-interop/assets/hindsight-project-hooks"),
            (project / ".codex", ROOT / "tests/fixtures/hindsight-0.2.5"),
        ):
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((source / name).read_bytes())
    settings = home / ".hindsight/coding-agent.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"optInOnly": True,
                                   "mapPathToBank": {str(project): "test-bank"}}),
                        encoding="utf-8")
    scripts = home / ".hindsight/coding-agents/dist"
    scripts.mkdir(parents=True)
    for name in UPGRADE.EVENT_SCRIPTS:
        (scripts / name).write_text("// fake installed script", encoding="utf-8")
    for name in (".codex/config.toml", ".codex/auth.json", ".claude/settings.json"):
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"sentinel-not-a-real-secret")
    return home, project, templates, settings


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_plan_does_not_write(installation):
    home, project, _, _ = installation
    before = snapshot(home), snapshot(project)
    report = UPGRADE.upgrade(home, project)
    assert report["status"] == "READY"
    assert tuple(report["before_sha256"]) in UPGRADE.KNOWN_PAIRS
    assert tuple(report["after_sha256"]) == UPGRADE.TARGET_PAIR
    assert (snapshot(home), snapshot(project)) == before


def test_apply_verifies_backup_and_is_idempotent(installation):
    home, project, templates, _ = installation
    original = snapshot(project)
    home_before = snapshot(home)
    report = UPGRADE.upgrade(home, project, apply=True)
    assert report["status"] == "UPDATED"
    backup = Path(report["backup"])
    for name in UPGRADE.FILES:
        assert (backup / name).read_bytes() == original[str(Path(".codex") / name)]
        assert (project / ".codex" / name).read_bytes() == (templates / name).read_bytes()
    assert json.loads((backup / "receipt.json").read_text())["before_sha256"] == report["before_sha256"]
    after = snapshot(project)
    assert UPGRADE.upgrade(home, project, apply=True)["status"] == "CURRENT"
    assert snapshot(project) == after
    assert snapshot(home) == home_before


def test_custom_hooks_are_preserved(installation):
    home, project, _, _ = installation
    hooks = project / ".codex/hooks.json"
    data = json.loads(hooks.read_text())
    data["custom"] = "keep this other automation"
    hooks.write_text(json.dumps(data), encoding="utf-8")
    before = snapshot(project)
    assert UPGRADE.upgrade(home, project, apply=True)["status"] == "NEEDS_REVIEW"
    assert snapshot(project) == before


@pytest.mark.parametrize("change", ["opt-out", "other-project", "missing-script", "changed-template"])
def test_preflight_blocks_without_project_changes(installation, change):
    home, project, templates, settings = installation
    data = json.loads(settings.read_text())
    if change == "opt-out":
        data["optInOnly"] = False
    elif change == "other-project":
        data["mapPathToBank"] = {str(project.parent / "other"): "test-bank"}
    elif change == "missing-script":
        (home / ".hindsight/coding-agents/dist" / UPGRADE.EVENT_SCRIPTS[0]).unlink()
    else:
        (templates / UPGRADE.FILES[0]).write_bytes(b"unverified replacement")
    settings.write_text(json.dumps(data), encoding="utf-8")
    before = snapshot(project)
    assert UPGRADE.upgrade(home, project, apply=True)["status"] == "BLOCKED"
    assert snapshot(project) == before


@pytest.mark.parametrize("data", [[], None, "string", 7])
def test_non_object_settings_are_rejected(installation, data):
    home, project, _, settings = installation
    settings.write_text(json.dumps(data), encoding="utf-8")
    before = snapshot(project)
    assert UPGRADE.upgrade(home, project, apply=True)["status"] == "BLOCKED"
    assert snapshot(project) == before


def test_second_write_failure_restores_both_files(installation, monkeypatch):
    home, project, _, _ = installation
    originals = [(project / ".codex" / name).read_bytes() for name in UPGRADE.FILES]
    write, calls = UPGRADE._write, []

    def fail_once(path, data):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("injected second write failure")
        write(path, data)

    monkeypatch.setattr(UPGRADE, "_write", fail_once)
    report = UPGRADE.upgrade(home, project, apply=True)
    assert report["status"] == "ROLLED_BACK"
    assert [(project / ".codex" / name).read_bytes() for name in UPGRADE.FILES] == originals
    assert [(Path(report["backup"]) / name).read_bytes() for name in UPGRADE.FILES] == originals


def test_rollback_failure_preserves_recovery_backup(installation, monkeypatch):
    home, project, _, _ = installation
    originals = [(project / ".codex" / name).read_bytes() for name in UPGRADE.FILES]
    write, calls = UPGRADE._write, []

    def fail_from_second_write(path, data):
        calls.append(path)
        if len(calls) >= 2:
            raise OSError("injected unavailable destination")
        write(path, data)

    monkeypatch.setattr(UPGRADE, "_write", fail_from_second_write)
    report = UPGRADE.upgrade(home, project, apply=True)
    assert report["status"] == "ROLLBACK_FAILED"
    assert "Restore both" in report["next"]
    assert [(Path(report["backup"]) / name).read_bytes() for name in UPGRADE.FILES] == originals
