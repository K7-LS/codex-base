from __future__ import annotations

import hashlib
import http.server
import importlib.util
import json
import os
import shutil
import subprocess
import threading
import tomllib
import zipfile
import base64
import ctypes
from pathlib import Path
from urllib.parse import quote

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


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _protect_for_current_windows_user(payload: bytes, entropy: bytes) -> bytes:
    payload_buffer = ctypes.create_string_buffer(payload)
    entropy_buffer = ctypes.create_string_buffer(entropy)
    input_blob = _DataBlob(
        len(payload),
        ctypes.cast(payload_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    entropy_blob = _DataBlob(
        len(entropy),
        ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _write_release_fixture(
    root: Path,
    *,
    gates: dict[str, str] | None = None,
) -> tuple[str, Path, dict[str, object]]:
    tag = "codex-v0.1.0"
    source = {
        "repository": "https://github.com/daniileliseev1337/codex-base",
        "commit": "1" * 40,
        "tree": "2" * 40,
        "transformation": "codex-native-v1",
    }
    lock = {
        "schema_version": 1,
        "target": "codex",
        "version": "0.1.0",
        "provenance": {"rendered_target": source},
        "components": {},
    }
    lock_bytes = _json_bytes(lock)
    foundation_script = b"exit 0\n"
    foundation_manifest = {
        "schema_version": 1,
        "protocol_version": 1,
        "engine_version": "0.1.0",
        "network": "offline",
        "commands": [
            "doctor",
            "install",
            "inventory",
            "plan",
            "rollback",
        ],
        "supported_powershell": ["5.1", "7"],
        "foundation_ps1_sha256": hashlib.sha256(
            foundation_script
        ).hexdigest(),
    }
    foundation_manifest_bytes = _json_bytes(foundation_manifest)
    entries = {
        ".codex/base/components.lock.json": lock_bytes,
        ".codex/base/foundation/0.1.0/VERSION": b"0.1.0\n",
        ".codex/base/foundation/0.1.0/foundation.ps1": foundation_script,
        ".codex/base/foundation/0.1.0/engine-manifest.json": (
            foundation_manifest_bytes
        ),
    }
    package_manifest = {
        "schema_version": 1,
        "target": "codex",
        "version": "0.1.0",
        "foundation_engine_version": "0.1.0",
        "files": [
            {
                "path": name,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
            for name, payload in sorted(entries.items())
        ],
    }
    package_manifest_bytes = _json_bytes(package_manifest)
    archive = root / "codex-base-0.1.0.zip"
    with zipfile.ZipFile(archive, "w") as package:
        for name, payload in entries.items():
            package.writestr(name, payload)
        package.writestr("package-manifest.json", package_manifest_bytes)
    manifest = {
        "target": "codex",
        "version": "0.1.0",
        "tag": tag,
        "channel": "stable",
        "asset": {
            "name": archive.name,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "bytes": archive.stat().st_size,
        },
        "package_manifest_sha256": hashlib.sha256(
            package_manifest_bytes
        ).hexdigest(),
        "components_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "source": source,
        "foundation_engine_version": "0.1.0",
        "foundation_engine_manifest_sha256": hashlib.sha256(
            foundation_manifest_bytes
        ).hexdigest(),
    }
    binding_keys = (
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
    evidence = {
        "release_binding": {key: manifest[key] for key in binding_keys},
        "FOUNDATION_SYNTHETIC": "PASS",
        "OFFLINE_CODEX_CONTENT": "PASS",
        "STATIC_TOKEN_ACCEPTANCE": "PASS",
        "CODEX_OFFLINE_INTEGRATION": "PASS",
        "CODEX_TESTS": "PASS",
        "CANDIDATE_OFFLINE": "PASS",
        "MATCHED_AB": "PASS",
        "CODEX_CANARY": "PASS",
        "FULL_RELEASE_CODEX": "PASS",
        "PROGRAM_RELEASE": "1/3",
    }
    evidence.update(gates or {})
    evidence["evidence_body_sha256"] = hashlib.sha256(
        _json_bytes(evidence)
    ).hexdigest()
    evidence_bytes = _json_bytes(evidence)
    manifest["acceptance_evidence_sha256"] = hashlib.sha256(
        evidence_bytes
    ).hexdigest()
    (root / "release-manifest.json").write_bytes(_json_bytes(manifest))
    (root / "components.lock.json").write_bytes(lock_bytes)
    (root / "acceptance-evidence.json").write_bytes(evidence_bytes)
    return tag, archive, manifest


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
    tag, archive, _ = _write_release_fixture(tmp_path)
    commands = []

    def runner(command):
        commands.append(list(command))
        return _completed(command)

    zip_path, _, foundation = sync.verify_downloaded_release(
        tmp_path, tag, runner
    )

    assert zip_path == archive
    assert foundation == (
        tmp_path
        / "verified-foundation"
        / "0.1.0"
        / "foundation.ps1"
    )
    assert foundation.read_bytes() == b"exit 0\n"
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


@pytest.mark.parametrize(
    "gate",
    ["FULL_RELEASE_CODEX", "MATCHED_AB", "CODEX_CANARY"],
)
def test_sync_fails_closed_when_any_release_gate_is_not_pass(
    repo_root, tmp_path, gate
):
    sync = _load_sync(repo_root)
    tag, _, _ = _write_release_fixture(
        tmp_path,
        gates={gate: "NOT_PASS"},
    )

    with pytest.raises(RuntimeError, match=gate):
        sync.verify_downloaded_release(
            tmp_path,
            tag,
            lambda command: _completed(command),
        )


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        ("package_manifest", "package manifest SHA-256"),
        ("external_lock", "components lock SHA-256"),
        ("embedded_lock", "embedded components lock"),
        ("evidence_binding", "release binding differs"),
    ],
)
def test_sync_rejects_any_cross_binding_mismatch(
    repo_root, tmp_path, tamper, message
):
    sync = _load_sync(repo_root)
    tag, archive, manifest = _write_release_fixture(tmp_path)
    if tamper == "package_manifest":
        manifest["package_manifest_sha256"] = "0" * 64
        (tmp_path / "release-manifest.json").write_bytes(
            _json_bytes(manifest)
        )
    elif tamper == "external_lock":
        (tmp_path / "components.lock.json").write_bytes(b"{}\n")
    elif tamper == "embedded_lock":
        with zipfile.ZipFile(archive) as package:
            payloads = {
                name: package.read(name)
                for name in package.namelist()
            }
        payloads[".codex/base/components.lock.json"] = b'{"tampered":true}\n'
        with zipfile.ZipFile(archive, "w") as package:
            for name, payload in payloads.items():
                package.writestr(name, payload)
        manifest["asset"]["sha256"] = hashlib.sha256(
            archive.read_bytes()
        ).hexdigest()
        manifest["asset"]["bytes"] = archive.stat().st_size
        (tmp_path / "release-manifest.json").write_bytes(
            _json_bytes(manifest)
        )
    else:
        evidence_path = tmp_path / "acceptance-evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["release_binding"]["version"] = "9.9.9"
        evidence.pop("evidence_body_sha256")
        evidence["evidence_body_sha256"] = hashlib.sha256(
            _json_bytes(evidence)
        ).hexdigest()
        evidence_bytes = _json_bytes(evidence)
        evidence_path.write_bytes(evidence_bytes)
        manifest["acceptance_evidence_sha256"] = hashlib.sha256(
            evidence_bytes
        ).hexdigest()
        (tmp_path / "release-manifest.json").write_bytes(
            _json_bytes(manifest)
        )

    with pytest.raises(RuntimeError, match=message):
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


def test_sync_automatically_rolls_back_when_post_install_doctor_fails(
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
            return _completed(
                command,
                stdout="codex-cli 0.146.0-alpha.3.1\n",
            )
        if (
            str(foundation) in command
            and command[command.index(str(foundation)) + 1] == "doctor"
        ):
            return _completed(command, returncode=30, stderr="drift")
        return _completed(command)

    with pytest.raises(RuntimeError, match="Foundation doctor failed"):
        sync.invoke_foundation(archive, foundation, runner=runner)

    foundation_actions = [
        command[command.index(str(foundation)) + 1]
        for command in commands
        if str(foundation) in command
    ]
    assert foundation_actions == ["plan", "install", "doctor", "rollback"]


def test_sync_rejects_unparseable_codex_client_version(repo_root):
    sync = _load_sync(repo_root)

    with pytest.raises(RuntimeError, match="codex-cli version"):
        sync.detect_codex_client(
            lambda command: _completed(command, stdout="unknown client\n")
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI contract")
def test_sync_connection_direct_and_vpn_never_require_a_proxy(
    repo_root, tmp_path, monkeypatch
):
    sync = _load_sync(repo_root)
    home = tmp_path / "home"
    state = home / ".llm-foundation"
    state.mkdir(parents=True)
    for mode in ("Direct", "VPN"):
        (state / "connection.json").write_text(
            json.dumps(
                {"schema_version": 1, "mode": mode, "proxy": None}
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("HTTP_PROXY", "http://stale.invalid:8080")
        monkeypatch.setenv("HTTPS_PROXY", "http://stale.invalid:8080")
        monkeypatch.setenv("ALL_PROXY", "socks5://stale.invalid:1080")
        with sync.connection_environment(home) as connection:
            assert connection == {
                "mode": mode,
                "uses_proxy": False,
                "proxy_type": None,
            }
            assert "HTTP_PROXY" not in os.environ
            assert "HTTPS_PROXY" not in os.environ
            assert "ALL_PROXY" not in os.environ
            assert os.environ["NO_PROXY"] == "*"
            assert os.environ["LLM_FOUNDATION_CONNECTION_MODE"] == mode
        assert os.environ["HTTP_PROXY"] == "http://stale.invalid:8080"
        assert os.environ["HTTPS_PROXY"] == "http://stale.invalid:8080"
        assert os.environ["ALL_PROXY"] == "socks5://stale.invalid:1080"


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI contract")
@pytest.mark.parametrize(
    ("proxy_type", "scheme", "all_proxy"),
    [
        ("HTTP", "http", False),
        ("HTTPS", "https", False),
        ("SOCKS5", "socks5h", True),
    ],
)
def test_sync_connection_supports_authenticated_proxy_types_without_leaking(
    repo_root,
    tmp_path,
    monkeypatch,
    proxy_type,
    scheme,
    all_proxy,
):
    sync = _load_sync(repo_root)
    home = tmp_path / "home"
    state = home / ".llm-foundation"
    state.mkdir(parents=True)
    profile = {
        "schema_version": 1,
        "mode": "Proxy",
        "proxy": {
            "type": proxy_type,
            "host": "proxy.example.test",
            "port": 8443,
            "auth": {
                "mode": "UsernamePassword",
                "username": "alice+ops",
            },
        },
    }
    (state / "connection.json").write_text(
        json.dumps(profile),
        encoding="utf-8",
    )
    password = "s e:c@r"
    encrypted = _protect_for_current_windows_user(
        password.encode("utf-16-le"),
        b"llm-foundation-connection-v1",
    )
    (state / "connection.cred").write_text(
        base64.b64encode(encrypted).decode("ascii") + "\n",
        encoding="ascii",
    )
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)

    with sync.connection_environment(home) as connection:
        expected = (
            f"{scheme}://alice%2Bops:s%20e%3Ac%40r@"
            "proxy.example.test:8443"
        )
        assert connection == {
            "mode": "Proxy",
            "uses_proxy": True,
            "proxy_type": proxy_type,
        }
        assert os.environ["HTTP_PROXY"] == expected
        assert os.environ["HTTPS_PROXY"] == expected
        if all_proxy:
            assert os.environ["ALL_PROXY"] == expected
        else:
            assert "ALL_PROXY" not in os.environ
        assert password not in json.dumps(connection)
        assert password not in (state / "connection.json").read_text("utf-8")

    assert "HTTP_PROXY" not in os.environ
    assert "HTTPS_PROXY" not in os.environ
    assert "ALL_PROXY" not in os.environ


def test_sync_check_applies_saved_connection_only_for_the_network_operation(
    repo_root, tmp_path, monkeypatch, capsys
):
    sync = _load_sync(repo_root)
    home = tmp_path / "home"
    state = home / ".llm-foundation"
    state.mkdir(parents=True)
    (state / "connection.json").write_text(
        json.dumps(
            {"schema_version": 1, "mode": "VPN", "proxy": None}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_BASE_TARGET_HOME", str(home))
    monkeypatch.setenv("HTTPS_PROXY", "http://stale.invalid:8080")
    monkeypatch.setattr(sync.shutil, "which", lambda name: "gh.exe")

    def discover():
        assert os.environ["LLM_FOUNDATION_CONNECTION_MODE"] == "VPN"
        assert "HTTPS_PROXY" not in os.environ
        return "codex-v1.2.3"

    monkeypatch.setattr(sync, "discover_latest_stable", discover)

    assert sync.main(["--check"]) == 0
    assert capsys.readouterr().out.strip() == "codex-v1.2.3"
    assert os.environ["HTTPS_PROXY"] == "http://stale.invalid:8080"
    assert "LLM_FOUNDATION_CONNECTION_MODE" not in os.environ


@pytest.mark.parametrize(
    "executable",
    [
        value
        for value in (shutil.which("pwsh"), shutil.which("powershell.exe"))
        if value
    ],
)
@pytest.mark.parametrize("mode", ["Direct", "VPN"])
def test_powershell_connection_runtime_keeps_direct_and_vpn_proxy_free(
    repo_root, tmp_path, executable, mode
):
    home = tmp_path / f"home-{Path(executable).stem}-{mode}"
    state = home / ".llm-foundation"
    state.mkdir(parents=True)
    (state / "connection.json").write_text(
        json.dumps(
            {"schema_version": 1, "mode": mode, "proxy": None}
        ),
        encoding="utf-8",
    )
    probe = tmp_path / f"probe-{Path(executable).stem}-{mode}.ps1"
    runtime = repo_root / "runtime" / "connection.ps1"
    probe.write_text(
        """
. $env:LLM_TEST_CONNECTION_RUNTIME
$Inside = Invoke-WithLlmConnection -HomePath $env:LLM_TEST_HOME -ScriptBlock {
    [ordered]@{
        mode = $env:LLM_FOUNDATION_CONNECTION_MODE
        has_http_proxy = Test-Path Env:HTTP_PROXY
        has_https_proxy = Test-Path Env:HTTPS_PROXY
        has_all_proxy = Test-Path Env:ALL_PROXY
        no_proxy = $env:NO_PROXY
    } | ConvertTo-Json -Compress
}
$Inside
[ordered]@{
    restored_https_proxy = $env:HTTPS_PROXY
} | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["HTTPS_PROXY"] = "http://stale.invalid:8080"
    environment["LLM_TEST_CONNECTION_RUNTIME"] = str(runtime)
    environment["LLM_TEST_HOME"] = str(home)
    result = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(probe),
        ],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert rows[0] == {
        "mode": mode,
        "has_http_proxy": False,
        "has_https_proxy": False,
        "has_all_proxy": False,
        "no_proxy": "*",
    }
    assert rows[1]["restored_https_proxy"] == (
        "http://stale.invalid:8080"
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI contract")
@pytest.mark.parametrize(
    "executable",
    [
        value
        for value in (shutil.which("pwsh"), shutil.which("powershell.exe"))
        if value
    ],
)
@pytest.mark.parametrize(
    ("proxy_type", "scheme", "uses_all_proxy"),
    [
        ("HTTP", "http", False),
        ("HTTPS", "https", False),
        ("SOCKS5", "socks5h", True),
    ],
)
def test_powershell_connection_runtime_applies_authenticated_proxy_safely(
    repo_root,
    tmp_path,
    executable,
    proxy_type,
    scheme,
    uses_all_proxy,
):
    home = tmp_path / (
        f"proxy-home-{Path(executable).stem}-{proxy_type}"
    )
    state = home / ".llm-foundation"
    state.mkdir(parents=True)
    username = "alice+ops"
    password = "s e:c@r"
    (state / "connection.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "Proxy",
                "proxy": {
                    "type": proxy_type,
                    "host": "proxy.example.test",
                    "port": 8443,
                    "auth": {
                        "mode": "UsernamePassword",
                        "username": username,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    encrypted = _protect_for_current_windows_user(
        password.encode("utf-16-le"),
        b"llm-foundation-connection-v1",
    )
    (state / "connection.cred").write_text(
        base64.b64encode(encrypted).decode("ascii") + "\n",
        encoding="ascii",
    )
    expected = (
        f"{scheme}://{quote(username, safe='')}:"
        f"{quote(password, safe='')}@proxy.example.test:8443"
    )
    probe = tmp_path / (
        f"proxy-probe-{Path(executable).stem}-{proxy_type}.ps1"
    )
    runtime = repo_root / "runtime" / "connection.ps1"
    probe.write_text(
        f"""
. $env:LLM_TEST_CONNECTION_RUNTIME
Invoke-WithLlmConnection -HomePath $env:LLM_TEST_HOME -ScriptBlock {{
    [ordered]@{{
        mode = $env:LLM_FOUNDATION_CONNECTION_MODE
        https_matches = $env:HTTPS_PROXY -ceq '{expected}'
        all_proxy_present = Test-Path Env:ALL_PROXY
    }} | ConvertTo-Json -Compress
}}
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["LLM_TEST_CONNECTION_RUNTIME"] = str(runtime)
    environment["LLM_TEST_HOME"] = str(home)
    result = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(probe),
        ],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "mode": "Proxy",
        "https_matches": True,
        "all_proxy_present": uses_all_proxy,
    }
    assert password not in result.stdout
    assert username not in result.stdout


@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="Windows curl.exe is required",
)
@pytest.mark.parametrize(
    "executable",
    [
        value
        for value in (shutil.which("pwsh"), shutil.which("powershell.exe"))
        if value
    ],
)
def test_powershell_connection_runtime_fetches_json_with_curl(
    repo_root, tmp_path, executable
):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            payload = b'{"status":"ok"}\n'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            return

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        Handler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        home = tmp_path / f"curl-home-{Path(executable).stem}"
        state = home / ".llm-foundation"
        state.mkdir(parents=True)
        (state / "connection.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "mode": "Direct",
                    "proxy": None,
                }
            ),
            encoding="utf-8",
        )
        probe = tmp_path / f"curl-probe-{Path(executable).stem}.ps1"
        probe.write_text(
            """
. $env:LLM_TEST_CONNECTION_RUNTIME
Invoke-WithLlmConnection -HomePath $env:LLM_TEST_HOME -ScriptBlock {
    $Result = Invoke-LlmJsonGet `
        -Uri $env:LLM_TEST_URI `
        -UserAgent 'llm-foundation-test/1' `
        -TimeoutSeconds 5
    $Result.status
}
""",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["LLM_TEST_CONNECTION_RUNTIME"] = str(
            repo_root / "runtime" / "connection.ps1"
        )
        environment["LLM_TEST_HOME"] = str(home)
        environment["LLM_TEST_URI"] = (
            f"http://127.0.0.1:{server.server_port}/release"
        )
        result = subprocess.run(
            [
                executable,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(probe),
            ],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip() == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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
    assert "Invoke-LlmJsonGet" in hook
    assert "Invoke-RestMethod" not in hook
    assert "connection.ps1" in hook
    assert "Invoke-WithLlmConnection" in hook
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
