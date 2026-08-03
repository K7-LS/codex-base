from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_base.final_evidence import compose_final_evidence  # noqa: E402


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _write_new(path: Path, value: object) -> None:
    if path.exists():
        raise RuntimeError("final evidence exists; refusing to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compose pre-publication Codex FULL evidence from an accepted "
            "candidate, the one authorized matched A/B, and a live canary."
        )
    )
    parser.add_argument("--candidate-evidence", required=True, type=Path)
    parser.add_argument("--matched-ab-evidence", required=True, type=Path)
    parser.add_argument("--canary-evidence", required=True, type=Path)
    parser.add_argument("--legacy-sync-bootstrap", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    final = compose_final_evidence(
        candidate=_load(arguments.candidate_evidence.resolve()),
        matched_ab=_load(arguments.matched_ab_evidence.resolve()),
        canary=_load(arguments.canary_evidence.resolve()),
        legacy_sync_bootstrap=arguments.legacy_sync_bootstrap,
    )
    _write_new(arguments.output.resolve(), final)
    print(
        json.dumps(
            {
                "FULL_RELEASE_CODEX": final["FULL_RELEASE_CODEX"],
                "PROGRAM_RELEASE": final["PROGRAM_RELEASE"],
                "RELEASE_INTEGRITY": final["RELEASE_INTEGRITY"],
                "output": str(arguments.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
