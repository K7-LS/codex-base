"""The managed Stop hook asks for review of actual high-impact changes only."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


HOOK = Path(__file__).parents[1] / "runtime" / "hooks" / "check_consequences.ps1"
SHELLS = [value for name in ("pwsh", "powershell.exe") if (value := shutil.which(name))]


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _hook(shell: str, repo: Path, active: bool = False) -> dict:
    completed = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(HOOK)],
        input=json.dumps({"cwd": str(repo), "hook_event_name": "Stop", "stop_hook_active": active}),
        text=True, capture_output=True, timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _run("git", "init", "-q", str(tmp_path), cwd=tmp_path)
    _run("git", "config", "user.name", "Test", cwd=tmp_path)
    _run("git", "config", "user.email", "test@example.invalid", cwd=tmp_path)
    (tmp_path / "app.py").write_text("def charge():\n    return 'once'\n", encoding="utf-8")
    _run("git", "add", "app.py", cwd=tmp_path)
    _run("git", "commit", "-qm", "initial", cwd=tmp_path)
    return tmp_path


@pytest.mark.parametrize("shell", SHELLS)
def test_payment_retry_requests_independent_review(repo: Path, shell: str) -> None:
    (repo / "app.py").write_text("def charge():\n    return retry_payment()\n", encoding="utf-8")
    output = _hook(shell, repo)
    assert output["decision"] == "block"
    assert "independent auditor" in output["reason"]
    assert _hook(shell, repo, active=True) == {}


@pytest.mark.parametrize("shell", SHELLS)
def test_unrelated_edit_is_silent(repo: Path, shell: str) -> None:
    (repo / "app.py").write_text("def greeting():\n    return 'hello'\n", encoding="utf-8")
    assert _hook(shell, repo) == {}


@pytest.mark.parametrize("shell", SHELLS)
def test_new_untracked_payment_file_is_reviewed(repo: Path, shell: str) -> None:
    (repo / "payment.py").write_text("def charge():\n    return retry_payment()\n", encoding="utf-8")
    assert _hook(shell, repo)["decision"] == "block"


def test_managed_hook_is_bound_to_packaged_script() -> None:
    hooks = json.loads((HOOK.parent.parent / "hooks.json").read_text(encoding="utf-8"))
    stop = hooks["hooks"]["Stop"][0]["hooks"][0]
    assert "check_consequences.ps1" in stop["commandWindows"]
    assert stop["timeout"] <= 10
