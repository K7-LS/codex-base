from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest


def _load_sync(repo_root):
    path = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "tools"
        / "sync_base.py"
    )
    spec = importlib.util.spec_from_file_location("sync_base_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _completed(command, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def test_sync_selects_stable_semver_and_rejects_prereleases(repo_root):
    sync = _load_sync(repo_root)
    releases = [
        {"tagName": "codex-v1.3.0", "isDraft": False, "isPrerelease": True},
        {"tagName": "codex-v1.2.9", "isDraft": False, "isPrerelease": False},
        {"tagName": "codex-v1.10.0", "isDraft": False, "isPrerelease": False},
        {"tagName": "other-v9.0.0", "isDraft": False, "isPrerelease": False},
    ]
    assert sync.select_latest_stable(releases) == "codex-v1.10.0"


def test_sync_verifies_release_and_every_asset_before_install(repo_root, tmp_path):
    sync = _load_sync(repo_root)
    tag = "codex-v0.1.0"
    archive = tmp_path / "codex-base-0.1.0.zip"
    package_manifest = b'{"schema_version":1,"target":"codex"}\n'
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("package-manifest.json", package_manifest)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (tmp_path / "release-manifest.json").write_text(
        json.dumps(
            {
                "target": "codex",
                "tag": tag,
                "channel": "stable",
                "asset": {"name": archive.name, "sha256": digest},
                "package_manifest_sha256": hashlib.sha256(
                    package_manifest
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "components.lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "acceptance-evidence.json").write_text(
        '{"FULL_RELEASE_CODEX":"PASS"}',
        encoding="utf-8",
    )
    commands = []

    def runner(command):
        commands.append(list(command))
        return _completed(command)

    zip_path, _ = sync.verify_downloaded_release(tmp_path, tag, runner)

    assert zip_path == archive
    assert commands[0][:3] == ["gh", "release", "verify"]
    verified_assets = {
        Path(command[4]).name
        for command in commands
        if command[:3] == ["gh", "release", "verify-asset"]
    }
    assert verified_assets == {
        archive.name,
        "release-manifest.json",
        "components.lock.json",
        "acceptance-evidence.json",
    }


def test_sync_fails_closed_when_full_release_is_not_pass(repo_root, tmp_path):
    sync = _load_sync(repo_root)
    tag = "codex-v0.1.0"
    archive = tmp_path / "codex-base-0.1.0.zip"
    package_manifest = b'{"schema_version":1,"target":"codex"}\n'
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("package-manifest.json", package_manifest)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (tmp_path / "release-manifest.json").write_text(
        json.dumps(
            {
                "target": "codex",
                "tag": tag,
                "channel": "stable",
                "asset": {"name": archive.name, "sha256": digest},
                "package_manifest_sha256": hashlib.sha256(
                    package_manifest
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "components.lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "acceptance-evidence.json").write_text(
        '{"FULL_RELEASE_CODEX":"NOT_PASS"}',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="FULL_RELEASE_CODEX"):
        sync.verify_downloaded_release(
            tmp_path,
            tag,
            lambda command: _completed(command),
        )


def test_sync_rejects_package_manifest_not_bound_by_release_manifest(
    repo_root, tmp_path
):
    sync = _load_sync(repo_root)
    tag = "codex-v0.1.0"
    archive = tmp_path / "codex-base-0.1.0.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(
            "package-manifest.json",
            b'{"schema_version":1,"target":"codex"}\n',
        )
    (tmp_path / "release-manifest.json").write_text(
        json.dumps(
            {
                "target": "codex",
                "tag": tag,
                "channel": "stable",
                "asset": {
                    "name": archive.name,
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                },
                "package_manifest_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "components.lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "acceptance-evidence.json").write_text(
        '{"FULL_RELEASE_CODEX":"PASS"}',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="package manifest SHA-256"):
        sync.verify_downloaded_release(
            tmp_path,
            tag,
            lambda command: _completed(command),
        )


def test_sync_detects_exact_codex_client_and_passes_generic_client_contract(
    repo_root, tmp_path, monkeypatch
):
    sync = _load_sync(repo_root)
    foundation = tmp_path / "foundation.ps1"
    foundation.write_text("exit 0\n", encoding="utf-8")
    archive = tmp_path / "candidate.zip"
    archive.write_bytes(b"candidate")
    target_home = tmp_path / "home"
    target_home.mkdir()
    monkeypatch.setenv("CODEX_BASE_TARGET_HOME", str(target_home))
    commands = []

    def runner(command):
        commands.append(list(command))
        if command[0] == "codex":
            return _completed(command, stdout="codex-cli 0.146.0-alpha.3.1\n")
        return _completed(command)

    sync.invoke_foundation(archive, foundation, runner=runner)

    foundation_commands = [
        command for command in commands if str(foundation) in command
    ]
    assert len(foundation_commands) == 3
    assert [
        command[command.index(str(foundation)) + 1]
        for command in foundation_commands
    ] == [
        "plan",
        "install",
        "doctor",
    ]
    for command in foundation_commands:
        client_id = command.index("-ClientId")
        client_version = command.index("-ClientVersion")
        assert command[client_id + 1] == "codex-cli"
        assert command[client_version + 1] == "0.146.0-alpha.3.1"


def test_sync_rejects_unparseable_codex_client_version(repo_root):
    sync = _load_sync(repo_root)

    with pytest.raises(RuntimeError, match="codex-cli version"):
        sync.detect_codex_client(
            lambda command: _completed(command, stdout="unknown client\n")
        )


def _run_hook(executable, script, home, fixture):
    environment = os.environ.copy()
    environment["CODEX_BASE_HOME_OVERRIDE"] = str(home)
    environment["CODEX_BASE_RELEASE_FIXTURE"] = str(fixture)
    return subprocess.run(
        [
            executable,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )


@pytest.mark.parametrize(
    "executable",
    [
        value
        for value in (shutil.which("pwsh"), shutil.which("powershell.exe"))
        if value
    ],
)
def test_session_start_version_check_is_silent_or_one_line_and_ttl_bounded(
    repo_root, tmp_path, executable
):
    script = repo_root / "runtime" / "hooks" / "check_release.ps1"
    fixture = tmp_path / "releases.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "tag_name": "codex-v0.2.0",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "2026-07-26T00:00:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )
    home = tmp_path / Path(executable).stem
    home.mkdir()
    (home / "VERSION").write_text("0.1.0\n", encoding="utf-8")

    first = _run_hook(executable, script, home, fixture)
    assert first.returncode == 0
    lines = [line for line in first.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    assert "$sync-base" in json.loads(lines[0])["systemMessage"]

    fixture.write_text("not json", encoding="utf-8")
    second = _run_hook(executable, script, home, fixture)
    assert second.returncode == 0
    assert second.stdout == ""
    assert second.stderr == ""


def test_runtime_has_only_minimal_one_way_hook_and_no_model_defaults(repo_root):
    hooks = json.loads((repo_root / "runtime" / "hooks.json").read_text("utf-8"))
    assert set(hooks["hooks"]) == {"SessionStart"}
    assert hooks["hooks"]["SessionStart"][0]["matcher"] == "^startup$"

    config = tomllib.loads((repo_root / "runtime" / "config.toml").read_text("utf-8"))
    assert "model" not in config
    assert "model_reasoning_effort" not in config
    assert "mcp_servers" not in config
    assert config["features"]["hooks"] is True

    hook = (repo_root / "runtime" / "hooks" / "check_release.ps1").read_text(
        "utf-8"
    )
    assert "Invoke-RestMethod -Method Get" in hook
    for forbidden in (
        "invoke-restmethod -method post",
        "invoke-webrequest -method post",
        "feedback",
        "telemetry",
        "session-report",
    ):
        assert forbidden not in hook.lower()

    metadata = (
        repo_root
        / "control-skills"
        / "sync-base"
        / "agents"
        / "openai.yaml"
    ).read_text(encoding="utf-8")
    assert "allow_implicit_invocation: false" in metadata
