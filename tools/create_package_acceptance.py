from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_base.promotion import create_package_acceptance  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create local employee-installer package acceptance only after "
            "immutable GitHub release verification."
        )
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--release-verification", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise SystemExit("package acceptance exists; refusing to overwrite")
    result = create_package_acceptance(
        arguments.manifest.resolve(),
        arguments.evidence.resolve(),
        arguments.release_verification.resolve(),
        arguments.output.resolve(),
    )
    print(
        json.dumps(
            {
                "target": result["target"],
                "package_acceptance": result["package_acceptance"],
                "output": str(arguments.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
