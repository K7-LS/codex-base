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
REQUIRED_FULL_RELEASE_GATES = (
    "FOUNDATION_SYNTHETIC",
    "OFFLINE_CODEX_CONTENT",
    "STATIC_TOKEN_ACCEPTANCE",
    "CODEX_OFFLINE_INTEGRATION",
    "CODEX_TESTS",
    "CANDIDATE_OFFLINE",
    "MATCHED_AB",
    "CODEX_CANARY",
    "FULL_RELEASE_CODEX",
)

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


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _release_binding(manifest: dict[str, object]) -> dict[str, object]:
    keys = (
        "target",
        "version",
        "tag",
        "asset",
        "package_manifest_sha256",
        "components_lock_sha256",
        "source",
        "foundation_engine_version",
        "foundation_engine_manifest_sha256",
    )
    if any(key not in manifest for key in keys):
        raise RuntimeError("release manifest binding is incomplete")
    return {key: manifest[key] for key in keys}


def _verify_evidence_body(evidence: dict[str, object]) -> None:
    body = dict(evidence)
    declared = body.pop("evidence_body_sha256", None)
    actual = hashlib.sha256(_json_bytes(body)).hexdigest()
    if declared != actual:
        raise RuntimeError("acceptance evidence body SHA-256 mismatch")


def _foundation_from_verified_package(
    release_dir: Path,
    archive: zipfile.ZipFile,
    package_manifest: dict[str, object],
    release_manifest: dict[str, object],
) -> Path:
    version = str(release_manifest.get("foundation_engine_version") or "")
    if (
        not re.fullmatch(r"\d+\.\d+\.\d+", version)
        or package_manifest.get("foundation_engine_version") != version
    ):
        raise RuntimeError("Foundation engine version binding differs")
    prefix = f".codex/base/foundation/{version}/"
    required = {
        "VERSION": prefix + "VERSION",
        "foundation.ps1": prefix + "foundation.ps1",
        "engine-manifest.json": prefix + "engine-manifest.json",
    }
    names = archive.namelist()
    payloads: dict[str, bytes] = {}
    for label, name in required.items():
        if names.count(name) != 1:
            raise RuntimeError(f"verified Foundation file differs: {label}")
        payloads[label] = archive.read(name)

    rows = {
        str(row.get("path")): row
        for row in package_manifest.get("files", [])
        if isinstance(row, dict)
    }
    for label, name in required.items():
        row = rows.get(name)
        payload = payloads[label]
        if (
            not isinstance(row, dict)
            or row.get("sha256")
            != hashlib.sha256(payload).hexdigest()
            or row.get("bytes") != len(payload)
        ):
            raise RuntimeError(
                f"Foundation package row differs: {label}"
            )

    if payloads["VERSION"].decode("utf-8").strip() != version:
        raise RuntimeError("Foundation VERSION differs")
    if hashlib.sha256(payloads["engine-manifest.json"]).hexdigest() != (
        release_manifest.get("foundation_engine_manifest_sha256")
    ):
        raise RuntimeError("Foundation engine manifest SHA-256 mismatch")
    engine_manifest = json.loads(
        payloads["engine-manifest.json"].decode("utf-8")
    )
    if (
        engine_manifest.get("schema_version") != 1
        or engine_manifest.get("protocol_version") != 1
        or engine_manifest.get("engine_version") != version
        or engine_manifest.get("network") != "offline"
        or engine_manifest.get("commands")
        != ["doctor", "install", "inventory", "plan", "rollback"]
        or engine_manifest.get("supported_powershell") != ["5.1", "7"]
        or engine_manifest.get("foundation_ps1_sha256")
        != hashlib.sha256(payloads["foundation.ps1"]).hexdigest()
    ):
        raise RuntimeError("Foundation engine contract differs")

    destination = release_dir / "verified-foundation" / version
    destination.mkdir(parents=True, exist_ok=False)
    for label, payload in payloads.items():
        (destination / label).write_bytes(payload)
    return destination / "foundation.ps1"


def verify_downloaded_release(
    release_dir: Path,
    tag: str,
    runner: Runner = _default_runner,
) -> tuple[Path, dict[str, object], Path]:
    _run_checked(runner, ["gh", "release", "verify", tag, "-R", REPOSITORY])
    match = TAG_PATTERN.fullmatch(tag)
    if not match:
        raise RuntimeError("release tag is invalid")
    version = ".".join(match.groups())
    expected_zip = release_dir / f"codex-base-{version}.zip"
    manifest_path = release_dir / "release-manifest.json"
    evidence_path = release_dir / "acceptance-evidence.json"
    lock_path = release_dir / "components.lock.json"
    for path in (manifest_path, evidence_path, lock_path):
        if not path.is_file():
            raise RuntimeError(f"missing release asset: {path.name}")
    if not expected_zip.is_file():
        raise RuntimeError(f"missing release asset: {expected_zip.name}")
    declared_assets = {
        expected_zip.name,
        *REQUIRED_ASSETS,
    }
    for name in sorted(declared_assets):
        _run_checked(
            runner,
            [
                "gh",
                "release",
                "verify-asset",
                tag,
                str(release_dir / name),
                "-R",
                REPOSITORY,
            ],
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("tag") != tag
        or manifest.get("target") != "codex"
        or manifest.get("version") != version
    ):
        raise RuntimeError("release manifest target/tag mismatch")
    if manifest.get("channel") != "stable":
        raise RuntimeError("release manifest is not stable")
    asset = manifest.get("asset")
    if not isinstance(asset, dict):
        raise RuntimeError("release manifest has no asset record")
    zip_path = release_dir / str(asset.get("name") or "")
    if zip_path != expected_zip:
        raise RuntimeError("release ZIP name differs")
    if (
        _sha256(zip_path) != asset.get("sha256")
        or zip_path.stat().st_size != asset.get("bytes")
    ):
        raise RuntimeError("release ZIP SHA-256 mismatch")
    source = manifest.get("source")
    if (
        not isinstance(source, dict)
        or str(source.get("repository") or "").removeprefix("https://")
        != "github.com/daniileliseev1337/codex-base"
        or not re.fullmatch(r"[0-9a-f]{40}", str(source.get("commit") or ""))
        or not re.fullmatch(r"[0-9a-f]{40}", str(source.get("tree") or ""))
        or source.get("transformation") != "codex-native-v1"
    ):
        raise RuntimeError("release source provenance differs")
    lock_bytes = lock_path.read_bytes()
    if hashlib.sha256(lock_bytes).hexdigest() != manifest.get(
        "components_lock_sha256"
    ):
        raise RuntimeError("components lock SHA-256 mismatch")
    external_lock = json.loads(lock_bytes)
    if not isinstance(external_lock, dict):
        raise RuntimeError("components lock must contain an object")
    provenance = external_lock.get("provenance")
    if (
        external_lock.get("target") != "codex"
        or external_lock.get("version") != version
        or not isinstance(provenance, dict)
        or provenance.get("rendered_target")
        != manifest.get("source")
    ):
        raise RuntimeError("components lock provenance differs")
    try:
        with zipfile.ZipFile(zip_path) as package:
            manifest_name = "package-manifest.json"
            if package.namelist().count(manifest_name) != 1:
                raise RuntimeError("release ZIP package manifest is missing or duplicated")
            package_manifest_bytes = package.read(manifest_name)
            embedded_lock_name = ".codex/base/components.lock.json"
            if package.namelist().count(embedded_lock_name) != 1:
                raise RuntimeError(
                    "embedded components lock is missing or duplicated"
                )
            embedded_lock = package.read(embedded_lock_name)
            if hashlib.sha256(package_manifest_bytes).hexdigest() != (
                manifest.get("package_manifest_sha256")
            ):
                raise RuntimeError("package manifest SHA-256 mismatch")
            if embedded_lock != lock_bytes:
                raise RuntimeError("embedded components lock differs")
            package_manifest = json.loads(package_manifest_bytes)
            if not isinstance(package_manifest, dict):
                raise RuntimeError(
                    "package manifest must contain an object"
                )
            foundation = _foundation_from_verified_package(
                release_dir,
                package,
                package_manifest,
                manifest,
            )
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"release ZIP package manifest is unreadable: {exc}") from exc
    if (
        package_manifest.get("target") != "codex"
        or package_manifest.get("version") != version
    ):
        raise RuntimeError("package manifest target/version differs")

    evidence_bytes = evidence_path.read_bytes()
    if hashlib.sha256(evidence_bytes).hexdigest() != manifest.get(
        "acceptance_evidence_sha256"
    ):
        raise RuntimeError("acceptance evidence asset SHA-256 mismatch")
    evidence = json.loads(evidence_bytes)
    if not isinstance(evidence, dict):
        raise RuntimeError("acceptance evidence must contain an object")
    _verify_evidence_body(evidence)
    if evidence.get("release_binding") != _release_binding(manifest):
        raise RuntimeError("acceptance evidence release binding differs")
    for gate in REQUIRED_FULL_RELEASE_GATES:
        if evidence.get(gate) != "PASS":
            raise RuntimeError(f"{gate} is not PASS")
    if evidence.get("PROGRAM_RELEASE") != "1/3":
        raise RuntimeError("PROGRAM_RELEASE is not 1/3")
    return zip_path, manifest, foundation


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
    installed = False
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
            if installed:
                rollback = runner(
                    [
                        executable,
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(foundation),
                        "rollback",
                        "-Home",
                        home,
                        "-Target",
                        "codex",
                    ],
                )
                if rollback.returncode != 0:
                    rollback_detail = (
                        rollback.stderr or rollback.stdout or ""
                    ).strip()
                    raise RuntimeError(
                        f"Foundation {command} failed: {detail}; "
                        "automatic rollback failed: "
                        f"{rollback_detail}"
                    )
            raise RuntimeError(f"Foundation {command} failed: {detail}")
        if command == "install":
            installed = True


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
            zip_path, _, foundation = verify_downloaded_release(
                release_dir,
                tag,
            )
            invoke_foundation(zip_path, foundation)
        print(f"Codex-base {tag} installed and verified.")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
