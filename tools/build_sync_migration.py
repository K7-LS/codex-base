"""Build a reviewable migration distribution; never publish or install it."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAG = "sync-base-migration-v1.0.0"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build(output: Path, root: Path = ROOT, *, for_publication: bool = False) -> dict:
    if output.exists():
        raise ValueError("Output already exists; preserve the previous candidate.")
    files = {
        "migrate-sync-base.ps1": (root / "migration/migrate-sync-base.ps1").read_bytes().replace(b"\r\n", b"\n"),
        "connection.ps1": (root / "runtime/connection.ps1").read_bytes().replace(b"\r\n", b"\n"),
        "README.md": (root / "migration/README.md").read_bytes().replace(b"\r\n", b"\n"),
    }
    script = files["migrate-sync-base.ps1"].decode("utf-8")
    runtime_pin = re.search(r"MigrationRuntimeSha256 = '([a-f0-9]{64})'", script)
    if not runtime_pin or sha256(files["connection.ps1"]) != runtime_pin[1]:
        raise ValueError("Connection runtime differs from the pinned published runtime.")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip())
    if for_publication and dirty:
        raise ValueError("Publication requires a clean committed source checkout.")
    output.mkdir(parents=True)
    archive_path = output / "sync-base-migration-1.0.0.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name, date_time=(2026, 9, 21, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    archive_bytes = archive_path.read_bytes()
    manifest = {
        "schema_version": 1,
        "status": "RELEASE_PREPARED" if for_publication else "CANDIDATE_UNPUBLISHED",
        "tag": TAG,
        "target": "codex",
        "migration_protocol": "codex-sync-migration-v1",
        "accepted_protocol": "professional-core-v1",
        "base_release": "codex-v0.2.2",
        "base_package_rebuilt": False,
        "source": {"repository": "https://github.com/K7-LS/codex-base", "commit": commit,
                   "worktree_dirty": dirty},
        "asset": {"name": archive_path.name, "bytes": len(archive_bytes), "sha256": sha256(archive_bytes)},
        "files": [{"path": name, "bytes": len(data), "sha256": sha256(data)}
                  for name, data in sorted(files.items())],
    }
    (output / "migration-release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--for-publication", action="store_true",
                        help="Require clean committed source and mark assets RELEASE_PREPARED; does not publish.")
    args = parser.parse_args()
    manifest = build(args.output.resolve(), for_publication=args.for_publication)
    print(json.dumps({"status": manifest["status"], "asset": manifest["asset"],
                      "source_worktree_dirty": manifest["source"]["worktree_dirty"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
