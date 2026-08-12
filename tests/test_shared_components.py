from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_shared_components_match_all_native_repositories(repo_root: Path):
    repos = repo_root.parent
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools" / "verify_shared_components.py"),
            str(repos / "codex-base"),
            str(repos / "claude-base-v2"),
            str(repos / "opencode-base"),
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
        "repositories": 3,
        "components": 5,
    }
