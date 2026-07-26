from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from codex_base.token_audit import audit_static_context  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Static Codex-base token audit")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "reports" / "static-token-audit.json",
    )
    args = parser.parse_args()
    report = audit_static_context(REPO_ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(report["results"], ensure_ascii=False, sort_keys=True))
    return 0 if report["results"]["STATIC_TOKEN_ACCEPTANCE"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
