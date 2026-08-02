from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest


POWERSHELLS = [
    value
    for value in (shutil.which("pwsh"), shutil.which("powershell.exe"))
    if value
]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _write_verified_release_fixture(
    destination: Path,
    *,
    unsafe_zip_path: bool = False,
) -> tuple[Path, str]:
    destination.mkdir()
    version = "1.2.3"
    tag = f"codex-v{version}"
    client_version = "0.146.0-alpha.3.1"
    foundation_version = "0.2.0"
    foundation_script = (
        b"param([string]$Command)\n"
        b"Write-Output ('{\"command\":\"' + $Command + '\"}')\n"
    )
    engine_manifest = _json_bytes(
        {
            "schema_version": 1,
            "engine_version": foundation_version,
            "protocol_version": 1,
            "network": "offline",
            "commands": [
                "doctor",
                "install",
                "inventory",
                "plan",
                "rollback",
            ],
            "supported_powershell": ["5.1", "7"],
            "foundation_ps1_sha256": _sha256_bytes(
                foundation_script
            ),
        }
    )
    foundation_payloads = {
        "VERSION": (foundation_version + "\n").encode("ascii"),
        "foundation.ps1": foundation_script,
        "engine-manifest.json": engine_manifest,
    }
    lock = _json_bytes(
        {
            "schema_version": 1,
            "target": "codex",
            "version": version,
            "components": {},
        }
    )
    foundation_prefix = (
        f".codex/base/foundation/{foundation_version}/"
    )
    package_files = [
        {
            "path": foundation_prefix + name,
            "sha256": _sha256_bytes(payload),
            "bytes": len(payload),
        }
        for name, payload in foundation_payloads.items()
    ]
    package_manifest = _json_bytes(
        {
            "schema_version": 1,
            "target": "codex",
            "version": version,
            "client": {
                "id": "codex-cli",
                "supported_version": client_version,
            },
            "foundation_engine_version": foundation_version,
            "files": package_files,
        }
    )
    asset_name = f"codex-base-{version}.zip"
    asset_path = destination / asset_name
    with zipfile.ZipFile(
        asset_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr("package-manifest.json", package_manifest)
        archive.writestr(
            ".codex/base/components.lock.json",
            lock,
        )
        for name, payload in foundation_payloads.items():
            archive.writestr(foundation_prefix + name, payload)
        if unsafe_zip_path:
            archive.writestr("../escape.txt", b"blocked\n")
    (destination / "components.lock.json").write_bytes(lock)
    asset = {
        "name": asset_name,
        "sha256": _sha256_bytes(asset_path.read_bytes()),
        "bytes": asset_path.stat().st_size,
    }
    source = {
        "repository": "https://github.com/example/codex-base",
        "commit": "a" * 40,
        "tree": "b" * 40,
        "transformation": "codex-native-v1",
    }
    binding = {
        "target": "codex",
        "version": version,
        "tag": tag,
        "asset": asset,
        "package_manifest_sha256": _sha256_bytes(package_manifest),
        "components_lock_sha256": _sha256_bytes(lock),
        "source": source,
        "foundation_engine_version": foundation_version,
        "foundation_engine_manifest_sha256": _sha256_bytes(
            engine_manifest
        ),
    }
    evidence = {
        "schema_version": 1,
        "target": "codex",
        **{
            name: "PASS"
            for name in (
                "FOUNDATION_SYNTHETIC",
                "OFFLINE_CODEX_CONTENT",
                "STATIC_TOKEN_ACCEPTANCE",
                "CODEX_OFFLINE_INTEGRATION",
                "CODEX_TESTS",
                "CANDIDATE_OFFLINE",
                "MATCHED_AB",
                "CODEX_CANARY",
                "FULL_RELEASE_CODEX",
                "RELEASE_INTEGRITY",
            )
        },
        "PROGRAM_RELEASE": "1/3",
        "release_binding": binding,
    }
    evidence_bytes = _json_bytes(evidence)
    (destination / "acceptance-evidence.json").write_bytes(
        evidence_bytes
    )
    manifest = {
        "schema_version": 1,
        **binding,
        "channel": "stable",
        "client": {
            "id": "codex-cli",
            "supported_version": client_version,
        },
        "requires": {
            "immutable_release": True,
            "release_attestation": True,
        },
        "acceptance_evidence_sha256": _sha256_bytes(evidence_bytes),
    }
    (destination / "release-manifest.json").write_bytes(
        _json_bytes(manifest)
    )
    return destination, tag


def _run_library_probe(
    executable: str,
    script: Path,
    policy: Path,
    probe: str,
) -> subprocess.CompletedProcess[str]:
    command = (
        f". '{script}' -PolicyPath '{policy}' -LibraryMode; "
        + probe
    )
    encoded = __import__("base64").b64encode(
        command.encode("utf-16-le")
    ).decode("ascii")
    return subprocess.run(
        [
            executable,
            "-NoProfile",
            "-EncodedCommand",
            encoded,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )


def test_sync_powershell_runtime_is_target_neutral_and_policy_driven(
    repo_root,
):
    script = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "tools"
        / "sync_base.ps1"
    )
    policy_path = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "sync-policy.json"
    )
    assert script.is_file()
    assert policy_path.is_file()
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    assert policy == {
        "schema_version": 1,
        "target": "codex",
        "repository": "daniileliseev1337/codex-base",
        "tag_prefix": "codex-v",
        "transformation": "codex-native-v1",
        "install_root": ".codex",
        "client": {
            "id": "codex-cli",
            "command": ["codex", "--version"],
            "acceptance": "PASS",
            "version_pattern": (
                r"^codex-cli "
                r"(?<version>[0-9]+\.[0-9]+\.[0-9]+"
                r"(?:-[0-9A-Za-z.-]+)?)$"
            ),
        },
        "evidence": {
            "style": "flat",
            "required_verdicts": [
                "FOUNDATION_SYNTHETIC",
                "OFFLINE_CODEX_CONTENT",
                "STATIC_TOKEN_ACCEPTANCE",
                "CODEX_OFFLINE_INTEGRATION",
                "CODEX_TESTS",
                "CANDIDATE_OFFLINE",
                "MATCHED_AB",
                "CODEX_CANARY",
                "FULL_RELEASE_CODEX",
                "RELEASE_INTEGRITY",
            ],
            "program_release": "1/3",
        },
    }
    source = script.read_text(encoding="utf-8").lower()
    for forbidden in (
        "daniileliseev1337",
        "codex-base",
        "claude-base",
        "opencode-base",
        "feedback",
        "telemetry",
        "release upload",
        "api post",
    ):
        assert forbidden not in source
    for required in (
        "gh release verify",
        "gh release verify-asset",
        "gh attestation verify",
        "plan",
        "install",
        "doctor",
        "rollback",
    ):
        assert required.lower() in source


def test_sync_control_skill_ships_only_the_canonical_powershell_updater(
    repo_root,
):
    tools = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "tools"
    )

    runtimes = sorted(
        path.name
        for path in tools.iterdir()
        if path.is_file() and path.suffix in {".ps1", ".py"}
    )

    assert runtimes == ["sync_base.ps1"]


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_sync_powershell_selects_latest_stable_semver(
    repo_root, executable
):
    script = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "tools"
        / "sync_base.ps1"
    )
    policy = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "sync-policy.json"
    )
    releases = json.dumps(
        [
            {
                "tagName": "codex-v1.2.9",
                "isDraft": False,
                "isPrerelease": False,
            },
            {
                "tagName": "codex-v1.10.0",
                "isDraft": False,
                "isPrerelease": False,
            },
            {
                "tagName": "codex-v9.0.0",
                "isDraft": False,
                "isPrerelease": True,
            },
            {
                "tagName": "other-v99.0.0",
                "isDraft": False,
                "isPrerelease": False,
            },
        ],
        separators=(",", ":"),
    ).replace("'", "''")
    result = _run_library_probe(
        executable,
        script,
        policy,
        (
            f"$Rows = '{releases}' | ConvertFrom-Json; "
            "Select-LlmStableRelease -Releases $Rows"
        ),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "codex-v1.10.0"

@pytest.mark.parametrize("executable", POWERSHELLS)
def test_sync_powershell_check_prints_selected_release(
    repo_root, executable, tmp_path
):
    script = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "tools"
        / "sync_base.ps1"
    )
    policy = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "sync-policy.json"
    )
    home = tmp_path / "home"
    runtime = home / ".codex" / "base" / "runtime" / "connection.ps1"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(
        "function Invoke-WithLlmConnection {\n"
        "  param([scriptblock]$ScriptBlock, [string]$HomePath)\n"
        "  & $ScriptBlock\n"
        "}\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh.cmd").write_text(
        "@echo off\r\n"
        'echo [{"tagName":"codex-v1.10.0","isDraft":false,'
        '"isPrerelease":false}]\r\n',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = str(bin_dir) + os.pathsep + environment["PATH"]

    result = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-PolicyPath",
            str(policy),
            "-TargetHome",
            str(home),
            "-Check",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "codex-v1.10.0"

    active = home / ".llm-foundation" / "state" / "codex" / "active.json"
    active.parent.mkdir(parents=True)
    active.write_text(
        json.dumps({"target": "codex", "release_version": "1.11.0"}),
        encoding="utf-8",
    )
    no_downgrade = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-PolicyPath",
            str(policy),
            "-TargetHome",
            str(home),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    assert no_downgrade.returncode == 0, no_downgrade.stdout + no_downgrade.stderr
    assert no_downgrade.stdout.strip() == (
        "No newer stable release: installed 1.11.0; latest is codex-v1.10.0."
    )


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_sync_powershell_rolls_back_after_post_install_doctor_failure(
    repo_root,
    executable,
):
    script = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "tools"
        / "sync_base.ps1"
    )
    policy = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "sync-policy.json"
    )
    result = _run_library_probe(
        executable,
        script,
        policy,
        (
            "$script:Calls = [Collections.Generic.List[string]]::new(); "
            "function Invoke-LlmFoundationCommand { "
            "param($Verified, [string]$Command, [string]$ClientVersion); "
            "$script:Calls.Add($Command); "
            "if ($Command -ceq 'doctor') { "
            "return [pscustomobject]@{ exit_code = 30; output = 'drift' } "
            "}; "
            "return [pscustomobject]@{ exit_code = 0; output = '' } "
            "}; "
            "$Verified = [pscustomobject]@{ "
            "asset_path = 'candidate.zip'; foundation_path = 'foundation.ps1'; "
            "client_id = 'codex-cli'; client_version = '1.2.3' }; "
            "try { "
            "Invoke-LlmVerifiedWorkflow -Verified $Verified "
            "-ClientVersion '1.2.3' "
            "} catch { Write-Output ('ERROR:' + $_.Exception.Message) }; "
            "Write-Output ($script:Calls -join ',')"
        ),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [
        "ERROR:Foundation doctor failed.",
        "plan,install,doctor,rollback",
    ]


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_sync_powershell_blocks_unaccepted_client_before_network(
    repo_root, executable, tmp_path
):
    script = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "tools"
        / "sync_base.ps1"
    )
    policy = json.loads(
        (
            repo_root
            / "control-skills"
            / "sync-base"
            / "sync-policy.json"
        ).read_text(encoding="utf-8")
    )
    policy["client"]["acceptance"] = "NOT_ACCEPTED"
    policy["client"]["version_pattern"] = None
    policy_path = tmp_path / "sync-policy.json"
    policy_path.write_text(
        json.dumps(policy, ensure_ascii=True),
        encoding="utf-8",
    )
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    result = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-File",
            str(script),
            "-PolicyPath",
            str(policy_path),
            "-TargetHome",
            str(fake_home),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "client release contract is not accepted" in combined.lower()
    assert "github cli" not in combined.lower()


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_sync_powershell_accepts_a_fully_bound_release_fixture(
    repo_root, executable, tmp_path
):
    release_dir, tag = _write_verified_release_fixture(
        tmp_path / "release"
    )
    script = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "tools"
        / "sync_base.ps1"
    )
    policy = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "sync-policy.json"
    )
    result = _run_library_probe(
        executable,
        script,
        policy,
        (
            f"$Verified = Assert-LlmReleaseFiles "
            f"-Directory '{release_dir}' -Tag '{tag}'; "
            "$Verified.client_version"
        ),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "0.146.0-alpha.3.1"


@pytest.mark.parametrize("executable", POWERSHELLS)
@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("gate", "acceptance evidence is not pass: codex_canary"),
        ("binding", "acceptance evidence binding differs: version"),
    ],
)
def test_sync_powershell_rejects_failed_gate_or_cross_bound_evidence(
    repo_root,
    executable,
    tmp_path,
    mutation,
    expected_error,
):
    release_dir, tag = _write_verified_release_fixture(
        tmp_path / "release"
    )
    evidence_path = release_dir / "acceptance-evidence.json"
    manifest_path = release_dir / "release-manifest.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if mutation == "gate":
        evidence["CODEX_CANARY"] = "NOT_RUN"
    else:
        evidence["release_binding"]["version"] = "9.9.9"
    evidence_bytes = _json_bytes(evidence)
    evidence_path.write_bytes(evidence_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["acceptance_evidence_sha256"] = _sha256_bytes(
        evidence_bytes
    )
    manifest_path.write_bytes(_json_bytes(manifest))

    script = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "tools"
        / "sync_base.ps1"
    )
    policy = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "sync-policy.json"
    )
    result = _run_library_probe(
        executable,
        script,
        policy,
        (
            f"Assert-LlmReleaseFiles "
            f"-Directory '{release_dir}' -Tag '{tag}'"
        ),
    )

    assert result.returncode != 0
    assert expected_error in (
        result.stdout + result.stderr
    ).lower()


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_sync_powershell_rejects_zip_path_traversal(
    repo_root, executable, tmp_path
):
    release_dir, tag = _write_verified_release_fixture(
        tmp_path / "release",
        unsafe_zip_path=True,
    )
    script = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "tools"
        / "sync_base.ps1"
    )
    policy = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "sync-policy.json"
    )
    result = _run_library_probe(
        executable,
        script,
        policy,
        (
            f"Assert-LlmReleaseFiles "
            f"-Directory '{release_dir}' -Tag '{tag}'"
        ),
    )
    assert result.returncode != 0
    assert "unsafe path" in (
        result.stdout + result.stderr
    ).lower()
