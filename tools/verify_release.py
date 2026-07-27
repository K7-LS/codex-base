from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_base.release_verification import (  # noqa: E402
    build_release_verification,
)


def _run(command: list[str]) -> bytes:
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"{command[0]} verification failed: {detail}")
    return result.stdout


def _write_new(path: Path, value: object) -> None:
    if path.exists():
        raise RuntimeError(
            "release verification already exists; refusing to overwrite"
        )
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
            "Verify one already-published immutable Codex release and write "
            "minimal local release-verification.json evidence."
        )
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--asset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--gh", default="gh")
    arguments = parser.parse_args()

    manifest_path = arguments.manifest.resolve()
    asset_path = arguments.asset.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repository = str(manifest["source"]["repository"]).removeprefix(
        "https://github.com/"
    ).rstrip("/")
    tag = str(manifest["tag"])
    gh = arguments.gh
    gh_version = _run([gh, "--version"]).decode(
        "utf-8", errors="replace"
    ).strip()
    release_api = json.loads(
        _run(
            [
                gh,
                "api",
                f"repos/{repository}/releases/tags/{tag}",
            ]
        )
    )
    release_attestation = _run(
        [
            gh,
            "release",
            "verify",
            tag,
            "-R",
            repository,
            "--format",
            "json",
        ]
    )
    asset_attestation = _run(
        [
            gh,
            "release",
            "verify-asset",
            tag,
            str(asset_path),
            "-R",
            repository,
            "--format",
            "json",
        ]
    )
    evidence = build_release_verification(
        manifest_path=manifest_path,
        asset_path=asset_path,
        release_api=release_api,
        release_attestation_output=release_attestation,
        asset_attestation_output=asset_attestation,
        gh_version=gh_version,
    )
    _write_new(arguments.output.resolve(), evidence)
    print(
        json.dumps(
            {
                "RELEASE_INTEGRITY": evidence["RELEASE_INTEGRITY"],
                "repository": repository,
                "tag": tag,
                "output": str(arguments.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
