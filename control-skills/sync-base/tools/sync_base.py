from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Sequence


REPOSITORY = "daniileliseev1337/codex-base"
TAG_PATTERN = re.compile(r"^codex-v(\d+)\.(\d+)\.(\d+)$")
REQUIRED_ASSETS = {
    "release-manifest.json",
    "components.lock.json",
    "acceptance-evidence.json",
}

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _run_checked(runner: Runner, command: Sequence[str]) -> str:
    result = runner(command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "command failed").strip()
        raise RuntimeError(f"{' '.join(command)}: {detail}")
    return result.stdout


def select_latest_stable(releases: list[dict[str, object]]) -> str:
    candidates: list[tuple[tuple[int, int, int], str]] = []
    for release in releases:
        tag = str(release.get("tagName") or "")
        match = TAG_PATTERN.fullmatch(tag)
        if (
            not match
            or bool(release.get("isDraft"))
            or bool(release.get("isPrerelease"))
        ):
            continue
        candidates.append(
            (tuple(int(part) for part in match.groups()), tag)
        )
    if not candidates:
        raise RuntimeError("no stable codex-vX.Y.Z release is available")
    return max(candidates)[1]


def discover_latest_stable(runner: Runner = _default_runner) -> str:
    output = _run_checked(
        runner,
        [
            "gh",
            "release",
            "list",
            "-R",
            REPOSITORY,
            "--limit",
            "100",
            "--json",
            "tagName,isDraft,isPrerelease",
        ],
    )
    return select_latest_stable(json.loads(output))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_downloaded_release(
    release_dir: Path,
    tag: str,
    runner: Runner = _default_runner,
) -> tuple[Path, dict[str, object]]:
    _run_checked(runner, ["gh", "release", "verify", tag, "-R", REPOSITORY])
    manifest_path = release_dir / "release-manifest.json"
    evidence_path = release_dir / "acceptance-evidence.json"
    lock_path = release_dir / "components.lock.json"
    for path in (manifest_path, evidence_path, lock_path):
        if not path.is_file():
            raise RuntimeError(f"missing release asset: {path.name}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("tag") != tag or manifest.get("target") != "codex":
        raise RuntimeError("release manifest target/tag mismatch")
    if manifest.get("channel") != "stable":
        raise RuntimeError("release manifest is not stable")
    asset = manifest.get("asset")
    if not isinstance(asset, dict):
        raise RuntimeError("release manifest has no asset record")
    zip_path = release_dir / str(asset.get("name") or "")
    if not zip_path.is_file():
        raise RuntimeError("release ZIP is missing")
    if _sha256(zip_path) != asset.get("sha256"):
        raise RuntimeError("release ZIP SHA-256 mismatch")
    try:
        with zipfile.ZipFile(zip_path) as package:
            manifest_name = "package-manifest.json"
            if package.namelist().count(manifest_name) != 1:
                raise RuntimeError("release ZIP package manifest is missing or duplicated")
            package_manifest = package.read(manifest_name)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"release ZIP package manifest is unreadable: {exc}") from exc
    if hashlib.sha256(package_manifest).hexdigest() != manifest.get(
        "package_manifest_sha256"
    ):
        raise RuntimeError("package manifest SHA-256 mismatch")

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("FULL_RELEASE_CODEX") != "PASS":
        raise RuntimeError("FULL_RELEASE_CODEX is not PASS")

    declared = {zip_path.name, *REQUIRED_ASSETS}
    for name in sorted(declared):
        path = release_dir / name
        _run_checked(
            runner,
            ["gh", "release", "verify-asset", tag, str(path), "-R", REPOSITORY],
        )
    return zip_path, manifest


def download_release(
    tag: str,
    destination: Path,
    runner: Runner = _default_runner,
) -> None:
    _run_checked(runner, ["gh", "release", "verify", tag, "-R", REPOSITORY])
    _run_checked(
        runner,
        [
            "gh",
            "release",
            "download",
            tag,
            "-R",
            REPOSITORY,
            "--dir",
            str(destination),
            "--pattern",
            "codex-base-*.zip",
            "--pattern",
            "release-manifest.json",
            "--pattern",
            "components.lock.json",
            "--pattern",
            "acceptance-evidence.json",
        ],
    )


def _powershell() -> str:
    for executable in ("pwsh", "powershell.exe"):
        resolved = shutil.which(executable)
        if resolved:
            return resolved
    raise RuntimeError("BLOCKED: PowerShell is required")


def _foundation_path() -> Path:
    override = os.environ.get("CODEX_BASE_FOUNDATION")
    if override:
        return Path(override)
    base = Path(os.environ.get("CODEX_BASE_HOME_OVERRIDE") or Path.home() / ".codex" / "base")
    candidates = sorted(
        (base / "foundation").glob("*/foundation.ps1"),
        key=lambda path: path.parent.name,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("BLOCKED: pinned Foundation engine is missing")
    return candidates[0]


def detect_codex_client(
    runner: Runner = _default_runner,
) -> tuple[str, str]:
    output = _run_checked(runner, ["codex", "--version"]).strip()
    match = re.fullmatch(
        r"codex-cli ([0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?)",
        output,
    )
    if not match:
        raise RuntimeError("codex-cli version could not be verified")
    return "codex-cli", match.group(1)


def invoke_foundation(
    zip_path: Path,
    foundation: Path,
    runner: Runner = _default_runner,
) -> None:
    executable = _powershell()
    home = os.environ.get("CODEX_BASE_TARGET_HOME") or str(Path.home())
    client_id, client_version = detect_codex_client(runner)
    for command in ("plan", "install", "doctor"):
        result = runner(
            [
                executable,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(foundation),
                command,
                "-Package",
                str(zip_path),
                "-Home",
                home,
                "-ClientId",
                client_id,
                "-ClientVersion",
                client_version,
            ],
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"Foundation {command} failed: {detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verified one-way Codex-base sync")
    parser.add_argument("--check", action="store_true", help="print latest stable tag only")
    args = parser.parse_args(argv)

    if shutil.which("gh") is None:
        print("BLOCKED: GitHub CLI (gh) is required", file=sys.stderr)
        return 2
    try:
        tag = discover_latest_stable()
        if args.check:
            print(tag)
            return 0
        with tempfile.TemporaryDirectory(prefix="codex-base-sync-") as temporary:
            release_dir = Path(temporary)
            download_release(tag, release_dir)
            zip_path, _ = verify_downloaded_release(release_dir, tag)
            invoke_foundation(zip_path, _foundation_path())
        print(f"Codex-base {tag} installed and verified.")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
