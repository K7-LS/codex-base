#!/usr/bin/env python3
"""Verify byte-identical K7 shared skills within and across native bases."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def tree_digest(root: Path) -> tuple[str, int]:
    rows = []
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        rows.append(f"{relative}\0{hashlib.sha256(payload).hexdigest()}\0{len(payload)}")
    digest = hashlib.sha256(("\n".join(rows) + "\n").encode("utf-8")).hexdigest()
    return digest, len(files)


def verify(repo: Path) -> dict[str, object]:
    lock_path = repo / "shared-components.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("schema_version") != 1 or lock.get("hash_algorithm") != "sha256-tree-v1":
        raise ValueError(f"invalid shared lock: {lock_path}")
    for row in lock.get("components", []):
        root = repo / "skills" / str(row["id"])
        if not root.is_dir():
            raise ValueError(f"missing shared component: {root}")
        actual, count = tree_digest(root)
        if actual != row["sha256"] or count != row["files"]:
            raise ValueError(f"shared component drift: {repo.name}/{row['id']}")
    return lock


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repos", nargs="+", type=Path)
    args = parser.parse_args()
    locks = [verify(repo.resolve()) for repo in args.repos]
    canonical = json.dumps(locks[0], sort_keys=True, ensure_ascii=False)
    if any(json.dumps(lock, sort_keys=True, ensure_ascii=False) != canonical for lock in locks[1:]):
        raise SystemExit("shared-components.lock.json differs across repositories")
    print(json.dumps({"status": "PASS", "repositories": len(locks), "components": len(locks[0]["components"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
