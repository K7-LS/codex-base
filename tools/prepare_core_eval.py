"""Record local source identities for a proposed evaluation; never call a model."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def prepare(repo_root: Path) -> dict:
    suite = repo_root / "evals/core/cases.json"
    suite_bytes = suite.read_bytes()
    cases = json.loads(suite_bytes)["cases"]
    paths = [repo_root / "AGENTS.md"]
    for directory in ("agents", "skills", "control-skills", "cold", "runtime"):
        paths.extend(
            path for path in (repo_root / directory).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        )
    inventory = {
        path.relative_to(repo_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths, key=lambda item: item.relative_to(repo_root).as_posix())
    }
    identity = "".join(f"{name}\0{digest}\n" for name, digest in inventory.items())
    return {
        "schema_version": 1,
        "status": "PREPARED_NOT_RUN",
        "kind": "local_source_inventory_not_release_evidence",
        "source_scope": ["AGENTS.md", "agents", "skills", "control-skills", "cold", "runtime"],
        "execution_authorized": False,
        "source_inventory_sha256": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "source_inventory": inventory,
        "suite_sha256": hashlib.sha256(suite_bytes).hexdigest(),
        "case_ids": [case["id"] for case in cases],
        "runs": [],
        "limitations": [
            "No client, model, tools or effective instruction loading has been tested.",
            "Local source hashes are not an installed-profile or release attestation.",
            "A comparison needs separately captured baseline and candidate identities.",
            "Case criteria are for reviewers; do not send them to the evaluated model.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = prepare(ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite an existing run or review record.
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(f"PREPARED_NOT_RUN: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
