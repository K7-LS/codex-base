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
from codex_base.core_acceptance import copy_core_artifacts, read_json  # noqa: E402


def _load(path: Path) -> dict[str, Any]:
    value = read_json(path.read_bytes())
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
            "candidate, package-bound professional-core evidence, and a live canary."
        )
    )
    parser.add_argument("--candidate-evidence", required=True, type=Path)
    parser.add_argument("--canary-evidence", required=True, type=Path)
    parser.add_argument("--core-behavior-evidence", type=Path)
    parser.add_argument("--install-only", action="store_true",
                        help="Use installation-integrity-v1; professional model behavior is NOT_PASS")
    parser.add_argument("--candidate-package", required=True, type=Path)
    parser.add_argument("--legacy-sync-bootstrap", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.install_only == bool(arguments.core_behavior_evidence):
        parser.error("select exactly one of --install-only or --core-behavior-evidence")
    core_path = arguments.core_behavior_evidence.resolve() if arguments.core_behavior_evidence else None
    final = compose_final_evidence(
        candidate=_load(arguments.candidate_evidence.resolve()),
        canary=_load(arguments.canary_evidence.resolve()),
        core_behavior=_load(core_path) if core_path else None,
        package_path=arguments.candidate_package.resolve(),
        artifact_root=core_path.parent if core_path else None,
        legacy_sync_bootstrap=arguments.legacy_sync_bootstrap,
        install_only=arguments.install_only,
    )
    if arguments.output.exists():
        raise RuntimeError("final evidence exists; refusing to overwrite")
    if core_path and arguments.output.resolve().parent != core_path.parent:
        copy_core_artifacts(final["core_behavior_evidence"], core_path.parent,
                            arguments.output.resolve().parent)
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
