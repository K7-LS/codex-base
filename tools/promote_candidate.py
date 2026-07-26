from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_base.promotion import promote_candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Promote accepted candidate bytes to stable release assets "
            "without rebuilding"
        )
    )
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--final-evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = promote_candidate(
        args.candidate.resolve(),
        args.final_evidence.resolve(),
        args.output.resolve(),
    )
    print(
        json.dumps(
            {
                "status": "STABLE_ASSETS_PREPARED",
                "zip": str(result.zip_path),
                "zip_sha256": result.zip_sha256,
                "note": (
                    "This command does not publish a GitHub release. "
                    "Owner authorization is still required."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
