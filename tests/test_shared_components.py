from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_shared_components_match_current_and_available_native_repositories(repo_root: Path):
    repos = repo_root.parent
    # An independent checkout always verifies itself. Missing optional siblings
    # are excluded from the verified count; existing but broken siblings fail.
    siblings = [
        path for path in (repos / "claude-base-v2", repos / "opencode-base")
        if path.is_dir()
    ]
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools" / "verify_shared_components.py"),
            str(repo_root),
            *(str(path) for path in siblings),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "status": "PASS",
        "repositories": 1 + len(siblings),
        "components": 5,
    }


def _copy_shared_repository(source: Path, destination: Path) -> Path:
    destination.mkdir()
    lock = source / "shared-components.lock.json"
    shutil.copyfile(lock, destination / lock.name)
    (destination / "tools").mkdir()
    shutil.copyfile(
        source / "tools/verify_shared_components.py",
        destination / "tools/verify_shared_components.py",
    )
    for row in json.loads(lock.read_text(encoding="utf-8"))["components"]:
        shutil.copytree(
            source / "skills" / row["id"],
            destination / "skills" / row["id"],
        )
    return destination


@pytest.mark.parametrize("sibling_count", [0, 1, 2])
def test_renamed_checkout_checks_each_available_sibling(
    repo_root: Path, tmp_path: Path, sibling_count: int
):
    candidate = _copy_shared_repository(repo_root, tmp_path / "candidate-r2")
    for name in ("claude-base-v2", "opencode-base")[:sibling_count]:
        _copy_shared_repository(repo_root, tmp_path / name)

    test_shared_components_match_current_and_available_native_repositories(candidate)


def test_current_checkout_drift_is_not_hidden_by_another_codex_checkout(
    repo_root: Path, tmp_path: Path
):
    candidate = _copy_shared_repository(repo_root, tmp_path / "candidate-r2")
    for name in ("codex-base", "claude-base-v2", "opencode-base"):
        _copy_shared_repository(repo_root, tmp_path / name)
    (candidate / "skills/facts-layer/SKILL.md").write_bytes(b"candidate drift\n")

    with pytest.raises(AssertionError, match="shared component drift"):
        test_shared_components_match_current_and_available_native_repositories(candidate)


@pytest.mark.parametrize("damage", ["content-drift", "missing-lock"])
def test_available_sibling_is_checked_when_the_other_is_absent(
    repo_root: Path, tmp_path: Path, damage: str
):
    candidate = _copy_shared_repository(repo_root, tmp_path / "candidate-r2")
    _copy_shared_repository(repo_root, tmp_path / "codex-base")
    sibling = _copy_shared_repository(repo_root, tmp_path / "claude-base-v2")
    if damage == "content-drift":
        (sibling / "skills/facts-layer/SKILL.md").write_bytes(b"sibling drift\n")
        expected = "shared component drift"
    else:
        (sibling / "shared-components.lock.json").unlink()
        expected = "FileNotFoundError"

    with pytest.raises(AssertionError, match=expected):
        test_shared_components_match_current_and_available_native_repositories(candidate)
