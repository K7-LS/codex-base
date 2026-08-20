from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_base.release import TARGET_REPOSITORY, build_release


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--foundation", required=True, type=Path)
    parser.add_argument("--dist", required=True, type=Path)
    parser.add_argument("--repository", default=TARGET_REPOSITORY)
    args = parser.parse_args()

    result = build_release(
        repo_root=ROOT,
        dist_root=args.dist.resolve(),
        version=args.version,
        foundation_root=args.foundation.resolve(),
        repository=args.repository,
    )
    print(result.zip_path)
    print(result.manifest_path)
    print(result.component_lock_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
