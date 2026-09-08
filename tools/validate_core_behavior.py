"""Validate an existing package-bound core bundle locally; never run models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_base.acceptance import release_binding_from_manifest  # noqa: E402
from codex_base.core_acceptance import read_json, validate_core_behavior  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    evidence = read_json(args.evidence.read_bytes())
    binding = release_binding_from_manifest(read_json(args.release_manifest.read_bytes()))
    result = validate_core_behavior(evidence, binding, package_path=args.package,
                                    artifact_root=args.evidence.resolve().parent)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
