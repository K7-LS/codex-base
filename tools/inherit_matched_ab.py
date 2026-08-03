from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_base.matched_ab import inherit_results  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bind an accepted four-call matched A/B to a package whose "
            "model-facing surface is byte-identical. Performs zero calls."
        )
    )
    parser.add_argument("--previous-evidence", required=True, type=Path)
    parser.add_argument("--previous-package", required=True, type=Path)
    parser.add_argument("--candidate-package", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    if output.exists():
        raise SystemExit("output already exists; refusing to overwrite")
    previous = json.loads(
        arguments.previous_evidence.resolve().read_text(encoding="utf-8")
    )
    evidence = inherit_results(
        previous=previous,
        previous_package=arguments.previous_package.resolve(),
        candidate_package=arguments.candidate_package.resolve(),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    print(
        json.dumps(
            {
                "MATCHED_AB": evidence["MATCHED_AB"],
                "evidence_mode": evidence["evidence_mode"],
                "new_paid_calls": 0,
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
