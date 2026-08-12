from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_shared_components_match_all_native_repositories(repo_root: Path):
    repos = repo_root.parent
    siblings = [repos / "claude-base-v2", repos / "opencode-base"]
    if os.environ.get("CI") and not all(path.is_dir() for path in siblings):
        # Cross-repository equality is enforced by the release-set job, which
        # checks out all three repositories. A single-repository CI checkout
        # still validates its own lock and bytes below.
        siblings = []
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools" / "verify_shared_components.py"),
            str(repos / "codex-base"),
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
        "repositories": 1 if not siblings else 3,
        "components": 5,
    }
