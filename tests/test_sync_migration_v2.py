"""The new bridge selects a signed stable Base without a CLI-version pin."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from test_sync_migration import fixture as legacy_fixture


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "migration/universal/migrate-sync-base.ps1"
SHELLS = [path for name in ("pwsh", "powershell.exe") if (path := shutil.which(name))]


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize(
    ("releases", "expected"),
    [
        (["0.2.9", "0.2.10"], "codex-v0.2.10"),
        (["0.2.3", "0.2.2"], "codex-v0.2.3"),
        (["0.2.2"], "BLOCKED"),
    ],
)
def test_bridge_selects_latest_supported_stable(shell: str, releases: list[str], expected: str):
    payload = json.dumps([[
        {"tag_name": f"codex-v{version}", "draft": False,
         "prerelease": False, "immutable": True}
        for version in releases
    ]])
    command = (
        f". {_ps_quote(str(SCRIPT))} -LibraryMode; "
        f"$script:mock_json = {_ps_quote(payload)}; "
        "function Invoke-MigrationGh { param($Arguments) return $script:mock_json }; "
        "try { Assert-MigrationLatestRelease; Write-Output $script:MigrationTag } "
        "catch { Write-Output 'BLOCKED' }"
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-Command", command], capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


def test_bridge_builder_binds_exact_files_and_source(tmp_path: Path):
    path = ROOT / "tools/build_sync_migration_v2.py"
    spec = importlib.util.spec_from_file_location("bridge_builder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    first = module.build(tmp_path / "first")
    second = module.build(tmp_path / "second")
    assert first["asset"] == second["asset"]
    assert first["tag"] == "sync-base-migration-v1.0.1"
    assert first["base_release"].endswith("at least 0.2.3")


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("client_version", ["0.153.1", "0.155.0-alpha.16.4"])
@pytest.mark.parametrize("mutation", ["none", "zip_drift", "attestation_failure"])
def test_bridge_plans_for_different_observed_cli_versions(
    tmp_path: Path, shell: str, client_version: str, mutation: str,
):
    distribution, assets, home, _ = legacy_fixture(tmp_path, client=client_version)
    shutil.copyfile(SCRIPT, distribution / "migrate-sync-base.ps1")
    old_zip = assets / "codex-base-0.2.2.zip"
    new_zip = assets / "codex-base-0.2.3.zip"
    with zipfile.ZipFile(old_zip) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    verifier_key = ".agents/skills/sync-base/tools/sync_base.ps1"
    verifier = entries[verifier_key].replace(b"0.2.2", b"0.2.3")
    verifier = verifier.replace(b"client_version='0.153.1'", b"client_version='0.0.0'")
    verifier = verifier.replace(b"supported_version='0.153.1'", b"supported_version='0.0.0'")
    verifier = verifier.replace(
        b"$script:MigrationAssetPins.PSObject.Properties['codex-base-0.2.3.zip'].Value.sha256",
        b"(Get-MigrationHash ([IO.File]::ReadAllBytes($Verified.asset_path)))",
    )
    entries[verifier_key] = verifier
    package = json.loads(entries["package-manifest.json"])
    package["version"] = "0.2.3"
    for row in package["files"]:
        if row["path"] == verifier_key:
            row["sha256"] = hashlib.sha256(verifier).hexdigest()
            row["bytes"] = len(verifier)
    entries["package-manifest.json"] = json.dumps(package).encode()
    with zipfile.ZipFile(new_zip, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    old_zip.unlink()
    (assets / "session-tools-codex-0.2.2.zip").rename(assets / "session-tools-codex-0.2.3.zip")
    manifest = json.loads((assets / "release-manifest.json").read_text())
    manifest.update(version="0.2.3", tag="codex-v0.2.3")
    manifest["package_manifest_sha256"] = hashlib.sha256(entries["package-manifest.json"]).hexdigest()
    manifest["client"] = {"id": "codex-cli", "supported_version": "0.0.0"}
    manifest["requires"] = {"immutable_release": True, "release_attestation": True}
    manifest["asset"] = {"name": new_zip.name, "sha256": hashlib.sha256(new_zip.read_bytes()).hexdigest(),
                         "bytes": new_zip.stat().st_size}
    session = assets / "session-tools-codex-0.2.3.zip"
    manifest["session_tools_asset"] = {"name": session.name, "sha256": hashlib.sha256(session.read_bytes()).hexdigest(),
                                       "bytes": session.stat().st_size}
    manifest["components_lock_sha256"] = hashlib.sha256((assets / "components.lock.json").read_bytes()).hexdigest()
    manifest["acceptance_evidence_sha256"] = hashlib.sha256((assets / "acceptance-evidence.json").read_bytes()).hexdigest()
    (assets / "release-manifest.json").write_text(json.dumps(manifest))
    if mutation == "zip_drift":
        with new_zip.open("ab") as stream:
            stream.write(b"changed after signing")
    releases = [[{"tag_name": "codex-v0.2.3", "draft": False,
                 "prerelease": False, "immutable": True}]]
    releases_path = tmp_path / "releases.json"
    releases_path.write_text(json.dumps(releases))
    work = tmp_path / "work"
    command = f"""
$ErrorActionPreference = 'Stop'
. {_ps_quote(str(distribution / 'migrate-sync-base.ps1'))} -LibraryMode
function gh {{ throw 'Unexpected unmocked gh invocation' }}
function Invoke-MigrationGh {{
    param([string[]]$Arguments)
    $operation = ($Arguments[0..1] -join ' ')
    if ({_ps_quote(mutation)} -ceq 'attestation_failure' -and $operation -ceq 'attestation verify') {{ throw 'Synthetic attestation failure' }}
    if ($Arguments[0] -ceq 'api') {{ return (Get-Content -LiteralPath {_ps_quote(str(releases_path))} -Raw) }}
    if ($operation -ceq 'release download') {{
        $destination = $Arguments[[array]::IndexOf($Arguments, '--dir') + 1]
        Get-ChildItem -LiteralPath {_ps_quote(str(assets))} -File | Copy-Item -Destination $destination
    }}
    return '{{}}'
}}
Invoke-SyncMigration -WorkDirectory {_ps_quote(str(work))} -TargetHome {_ps_quote(str(home))} -Mode Plan
"""
    probe = tmp_path / "probe.ps1"
    probe.write_text(command, encoding="utf-8-sig")
    result = subprocess.run([shell, "-NoProfile", "-File", str(probe)], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=60)
    if mutation == "none":
        assert result.returncode == 0, result.stdout + result.stderr
        plan = json.loads((work / "plan.json").read_text())
        assert plan["client"] == {"id": "codex-cli", "supported_version": "0.0.0"}
        assert plan["release_version"] == "0.2.3"
    else:
        assert result.returncode != 0
        assert not (work / "assets" / "validator-called.txt").exists()
    assert not (home / "installed-marker.txt").exists()
