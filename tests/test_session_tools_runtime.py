from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import textwrap
import time
import zipfile

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
UPDATER = REPOSITORY_ROOT / "runtime" / "update-session-tools.ps1"
POWERSHELLS = [
    value
    for value in (shutil.which("pwsh.exe"), shutil.which("powershell.exe"))
    if value
]
REPOSITORY = "K7-LS/codex-base"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _find_csharp_compiler() -> Path | None:
    candidates: list[Path] = []
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        root = os.environ.get(variable)
        if root:
            candidates.extend(
                Path(root).glob(
                    "Microsoft Visual Studio/*/*/MSBuild/Current/Bin/Roslyn/csc.exe"
                )
            )
    framework = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")
    if framework.is_file():
        candidates.append(framework)
    return sorted(candidates)[0] if candidates else None


def _compile_fake_gh(output: Path) -> None:
    compiler = _find_csharp_compiler()
    assert compiler is not None, "C# compiler is unavailable"
    source = output.with_suffix(".cs")
    source.write_text(
        textwrap.dedent(
            r'''
            using System;
            using System.Collections.Generic;
            using System.IO;
            using System.Linq;
            using System.Text;
            using System.Threading;

            internal static class FakeGh
            {
                private static void Log(string[] args)
                {
                    string path = Environment.GetEnvironmentVariable("FAKE_GH_LOG");
                    if (String.IsNullOrWhiteSpace(path)) return;
                    string joined = String.Join("\0", args);
                    string encoded = Convert.ToBase64String(Encoding.UTF8.GetBytes(joined));
                    File.AppendAllText(path, encoded + Environment.NewLine, new UTF8Encoding(false));
                }

                private static string ValueAfter(string[] args, string option)
                {
                    int index = Array.IndexOf(args, option);
                    if (index < 0 || index + 1 >= args.Length) return null;
                    return args[index + 1];
                }

                public static int Main(string[] args)
                {
                    Log(args);
                    int sleep;
                    if (Int32.TryParse(Environment.GetEnvironmentVariable("FAKE_GH_SLEEP_MS"), out sleep)
                        && sleep > 0) Thread.Sleep(sleep);
                    string fail = Environment.GetEnvironmentVariable("FAKE_GH_FAIL_MATCH");
                    string command = String.Join(" ", args);
                    if (!String.IsNullOrEmpty(fail) && command.IndexOf(fail, StringComparison.Ordinal) >= 0)
                        return 23;

                    if (args.Length >= 2 && args[0] == "release" && args[1] == "list")
                    {
                        Console.OutputEncoding = new UTF8Encoding(false);
                        Console.Write(Environment.GetEnvironmentVariable("FAKE_GH_RELEASE_LIST") ?? "[]");
                        return 0;
                    }
                    if (args.Length >= 2 && args[0] == "release" && args[1] == "download")
                    {
                        string fixture = Environment.GetEnvironmentVariable("FAKE_GH_FIXTURE");
                        string destination = ValueAfter(args, "--dir");
                        if (String.IsNullOrWhiteSpace(fixture) || String.IsNullOrWhiteSpace(destination))
                            return 24;
                        Directory.CreateDirectory(destination);
                        foreach (string pattern in args.Where((value, index) => index > 0 && args[index - 1] == "--pattern"))
                        {
                            string source = Path.Combine(fixture, pattern);
                            if (!File.Exists(source)) return 25;
                            File.Copy(source, Path.Combine(destination, pattern), true);
                        }
                        return 0;
                    }
                    if (args.Length >= 2 && args[0] == "release" && args[1] == "verify") return 0;
                    if (args.Length >= 2 && args[0] == "release" && args[1] == "verify-asset") return 0;
                    if (args.Length >= 2 && args[0] == "attestation" && args[1] == "verify") return 0;
                    return 26;
                }
            }
            '''
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(compiler), "/nologo", "/target:exe", f"/out:{output}", str(source)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="session")
def fake_gh(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("codex-fake-gh")
    executable = root / "gh.exe"
    _compile_fake_gh(executable)
    return executable


def _write_release_fixture(root: Path, payload: bytes) -> dict[str, object]:
    root.mkdir(parents=True)
    version = "0.1.4"
    tag = f"codex-v{version}"
    tool_record = {
        "id": "ru-writing-style",
        "files": [
            {
                "path": "SKILL.md",
                "sha256": _sha256_bytes(payload),
                "bytes": len(payload),
            }
        ],
    }
    session_manifest = {
        "schema_version": 1,
        "target": "codex",
        "release_tag": tag,
        "base_version": version,
        "tools": [tool_record],
    }
    session_manifest_bytes = _json_bytes(session_manifest)
    asset_name = f"session-tools-codex-{version}.zip"
    asset_path = root / asset_name
    with zipfile.ZipFile(asset_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in {
            "session-tools-manifest.json": session_manifest_bytes,
            "tools/ru-writing-style/SKILL.md": payload,
        }.items():
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100644 << 16)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    release_manifest = {
        "schema_version": 1,
        "target": "codex",
        "version": version,
        "tag": tag,
        "channel": "stable",
        "client": {
            "id": "codex-cli",
            "supported_version": "0.146.0-alpha.3.1",
        },
        "foundation_engine_version": "0.3.0",
        "foundation_engine_manifest_sha256": "1" * 64,
        "source": {
            "repository": "https://github.com/K7-LS/codex-base",
            "commit": "a" * 40,
            "tree": "b" * 40,
            "transformation": "codex-native-v1",
        },
        "asset": {
            "name": f"codex-base-{version}.zip",
            "sha256": "2" * 64,
            "bytes": 123,
        },
        "package_manifest_sha256": "3" * 64,
        "components_lock_sha256": "4" * 64,
        "session_tools_asset": {
            "name": asset_name,
            "sha256": _sha256_bytes(asset_path.read_bytes()),
            "bytes": asset_path.stat().st_size,
            "manifest_sha256": _sha256_bytes(session_manifest_bytes),
            "tool_count": 1,
            "file_count": 1,
        },
        "requires": {
            "immutable_release": True,
            "release_attestation": True,
            "verification_commands": [
                f"gh release verify {tag} -R {REPOSITORY}",
                (
                    f"gh release verify-asset {tag} codex-base-{version}.zip "
                    f"-R {REPOSITORY}"
                ),
            ],
        },
        "acceptance_evidence_sha256": "5" * 64,
        "promoted_from_candidate_manifest_sha256": "6" * 64,
    }
    release_manifest_bytes = _json_bytes(release_manifest)
    (root / "release-manifest.json").write_bytes(release_manifest_bytes)
    return {
        "tag": tag,
        "version": version,
        "asset_name": asset_name,
        "asset_path": asset_path,
        "release_manifest_bytes": release_manifest_bytes,
        "session_manifest_bytes": session_manifest_bytes,
        "tool_record": tool_record,
    }


def _rewrite_session_asset(
    fixture: Path,
    manifest_bytes: bytes,
    payload: bytes,
    *,
    payload_mode: int = 0o100644,
) -> None:
    release_path = fixture / "release-manifest.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    asset_path = fixture / release["session_tools_asset"]["name"]
    with zipfile.ZipFile(asset_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content, mode in (
            ("session-tools-manifest.json", manifest_bytes, 0o100644),
            ("tools/ru-writing-style/SKILL.md", payload, payload_mode),
        ):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    session = release["session_tools_asset"]
    session["sha256"] = _sha256_bytes(asset_path.read_bytes())
    session["bytes"] = asset_path.stat().st_size
    session["manifest_sha256"] = _sha256_bytes(manifest_bytes)
    release_path.write_bytes(_json_bytes(release))


def _state_root(home: Path) -> Path:
    return home / ".llm-foundation" / "state" / "session-tools" / "codex"


def _fingerprint(path: Path) -> str:
    if not path.exists():
        return "absent"
    if path.is_file():
        return _sha256_bytes(path.read_bytes())
    canonical = bytearray()
    for file in sorted(
        (item for item in path.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(path).as_posix(),
    ):
        relative = file.relative_to(path).as_posix()
        canonical.extend(f"{relative}\0{_sha256_bytes(file.read_bytes())}\n".encode())
    return _sha256_bytes(bytes(canonical))


def _stopwatch_contract() -> tuple[int, int, int, int, int]:
    frequency = ctypes.c_longlong()
    counter = ctypes.c_longlong()
    assert ctypes.windll.kernel32.QueryPerformanceFrequency(ctypes.byref(frequency))
    assert ctypes.windll.kernel32.QueryPerformanceCounter(ctypes.byref(counter))
    start = counter.value
    return (
        start,
        start + frequency.value * 22,
        start + frequency.value * 25,
        start + frequency.value * 30,
        frequency.value,
    )


def _write_receipt(home: Path) -> Path:
    launcher = home / ".llm-foundation" / "bin" / "codex-managed.exe"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"fake launcher\n")
    vendor = home / "bin" / "codex.exe"
    vendor.parent.mkdir(parents=True)
    vendor.write_bytes(b"fake vendor\n")
    receipt = launcher.with_suffix(".receipt.json")
    receipt.write_bytes(
        _json_bytes(
            {
                "schema_version": 1,
                "target": "codex",
                "launcher_path": str(launcher),
                "launcher_sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
                "updater_path": str(UPDATER),
                "vendor_executable_path": str(vendor),
            }
        )
    )
    return receipt


def _environment(home: Path, fixture: Path, fake_gh: Path, log: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONIOENCODING", None)
    environment["USERPROFILE"] = str(home)
    environment["CODEX_BASE_HOME_OVERRIDE"] = str(home / ".codex" / "base")
    environment["FAKE_GH_FIXTURE"] = str(fixture)
    environment["FAKE_GH_LOG"] = str(log)
    environment["FAKE_GH_RELEASE_LIST"] = json.dumps(
        [
            {
                "tagName": "codex-v0.1.4",
                "isDraft": False,
                "isPrerelease": False,
                "publishedAt": "2026-08-10T00:00:00Z",
            }
        ],
        separators=(",", ":"),
    )
    environment["PATH"] = str(fake_gh.parent) + os.pathsep + environment.get("PATH", "")
    return environment


def _run_managed(
    host: str,
    environment: dict[str, str],
    *,
    start_offset_seconds: int = 0,
) -> subprocess.CompletedProcess[str]:
    start, mutation, kill, deadline, frequency = _stopwatch_contract()
    start += start_offset_seconds * frequency
    mutation += start_offset_seconds * frequency
    kill += start_offset_seconds * frequency
    deadline += start_offset_seconds * frequency
    return subprocess.run(
        [
            host,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(UPDATER),
            "-ManagedPreflight",
            "-TransactionId",
            "12345678-1234-1234-1234-123456789abc",
            "-StartTick",
            str(start),
            "-MutationCutoffTick",
            str(mutation),
            "-KillTick",
            str(kill),
            "-HardDeadlineTick",
            str(deadline),
            "-StopwatchFrequency",
            str(frequency),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=35,
    )


def _run_fallback(
    host: str, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            host,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(UPDATER),
            "-HookFallback",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=35,
    )


def _case(
    tmp_path: Path, fake_gh: Path
) -> tuple[dict[str, str], Path, Path, Path, dict[str, object]]:
    payload = "---\nname: ru-writing-style\n---\n\nПиши ясно.\n".encode("utf-8")
    fixture = tmp_path / "fixture"
    expected = _write_release_fixture(fixture, payload)
    home = tmp_path / "Профиль с пробелом"
    _write_receipt(home)
    log = tmp_path / "gh.log"
    return _environment(home, fixture, fake_gh, log), home, fixture, log, expected


def _gh_calls(path: Path) -> list[list[str]]:
    import base64

    return [
        base64.b64decode(line).decode("utf-8").split("\0")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


@pytest.mark.parametrize("host", POWERSHELLS)
def test_managed_preflight_verifies_stable_release_and_installs_unicode_skill(
    tmp_path: Path, host: str, fake_gh: Path
) -> None:
    environment, home, _, log, expected = _case(tmp_path, fake_gh)
    payload = "---\nname: ru-writing-style\n---\n\nПиши ясно.\n".encode("utf-8")

    result = _run_managed(host, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    destination = home / ".agents" / "skills" / "ru-writing-style" / "SKILL.md"
    assert destination.read_bytes() == payload
    state_path = (
        home
        / ".llm-foundation"
        / "state"
        / "session-tools"
        / "codex"
        / "state.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(state) == {
        "schema_version",
        "target",
        "release_tag",
        "release_version",
        "release_manifest_sha256",
        "session_manifest_sha256",
        "verified_at",
        "tools",
    }
    assert state["schema_version"] == 1
    assert state["target"] == "codex"
    assert state["release_tag"] == expected["tag"]
    assert state["release_version"] == expected["version"]
    assert state["release_manifest_sha256"] == _sha256_bytes(
        expected["release_manifest_bytes"]
    )
    assert state["session_manifest_sha256"] == _sha256_bytes(
        expected["session_manifest_bytes"]
    )
    assert state["tools"] == [
        {
            "id": "ru-writing-style",
            "destination": str(destination.parent),
            "ownership_marker": "session-tools-v1:codex:ru-writing-style",
            "files": expected["tool_record"]["files"],
        }
    ]
    calls = _gh_calls(log)
    assert ["release", "verify", expected["tag"], "-R", REPOSITORY] in calls
    verified_assets = [call[3] for call in calls if call[:2] == ["release", "verify-asset"]]
    assert {Path(path).name for path in verified_assets} == {
        "release-manifest.json",
        expected["asset_name"],
    }
    attested_assets = [call[2] for call in calls if call[:2] == ["attestation", "verify"]]
    assert {Path(path).name for path in attested_assets} == {
        "release-manifest.json",
        expected["asset_name"],
    }
    assert not (
        home
        / ".llm-foundation"
        / "state"
        / "session-tools"
        / "codex"
        / "active-transaction.json"
    ).exists()


@pytest.mark.parametrize("host", POWERSHELLS)
def test_same_stable_tag_is_a_strict_noop(
    tmp_path: Path, host: str, fake_gh: Path
) -> None:
    environment, home, _, log, _ = _case(tmp_path, fake_gh)
    first = _run_managed(host, environment)
    assert first.returncode == 0, first.stdout + first.stderr
    destination = home / ".agents" / "skills" / "ru-writing-style" / "SKILL.md"
    state = _state_root(home) / "state.json"
    before = (destination.read_bytes(), state.read_bytes())
    log.unlink()

    second = _run_managed(host, environment)

    assert second.returncode == 0, second.stdout + second.stderr
    assert (destination.read_bytes(), state.read_bytes()) == before
    assert _gh_calls(log) == [
        [
            "release",
            "list",
            "-R",
            REPOSITORY,
            "--limit",
            "20",
            "--json",
            "tagName,isDraft,isPrerelease,publishedAt",
        ]
    ]
    update_records = (
        _state_root(home) / "update.log"
    ).read_text(encoding="utf-8").splitlines()
    assert json.loads(update_records[-1])["result"] == "NO_UPDATE"


def test_tampered_state_file_bytes_blocks_noop_as_state_drift(
    tmp_path: Path, fake_gh: Path
) -> None:
    environment, home, _, log, _ = _case(tmp_path, fake_gh)
    first = _run_managed(POWERSHELLS[0], environment)
    assert first.returncode == 0, first.stdout + first.stderr
    state_path = _state_root(home) / "state.json"
    state_text = state_path.read_text(encoding="utf-8")
    tampered, substitutions = re.subn(
        r'("bytes"\s*:\s*)[0-9]+', r"\g<1>-1", state_text, count=1
    )
    assert substitutions == 1
    state_path.write_text(tampered, encoding="utf-8")
    destination = home / ".agents" / "skills" / "ru-writing-style" / "SKILL.md"
    before = destination.read_bytes()
    log.unlink()

    second = _run_managed(POWERSHELLS[0], environment)

    assert second.returncode == 0, second.stdout + second.stderr
    assert destination.read_bytes() == before
    assert not (_state_root(home) / "active-transaction.json").exists()
    records = (_state_root(home) / "update.log").read_text(encoding="utf-8").splitlines()
    record = json.loads(records[-1])
    assert record["reason"] == "BLOCKED_STATE_DRIFT"
    assert _gh_calls(log) == [
        [
            "release",
            "list",
            "-R",
            REPOSITORY,
            "--limit",
            "20",
            "--json",
            "tagName,isDraft,isPrerelease,publishedAt",
        ]
    ]


@pytest.mark.parametrize("declared_count", [0, 2])
def test_protocol_one_rejects_zero_or_multiple_tools_before_mutation(
    tmp_path: Path, fake_gh: Path, declared_count: int
) -> None:
    environment, home, fixture, _, _ = _case(tmp_path, fake_gh)
    release_path = fixture / "release-manifest.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release["session_tools_asset"]["tool_count"] = declared_count
    release_path.write_bytes(_json_bytes(release))

    result = _run_fallback(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / ".agents" / "skills").exists()
    assert not (_state_root(home) / "active-transaction.json").exists()
    assert "BLOCKED_MULTI_TOOL_ASSET" in (
        _state_root(home) / "update.log"
    ).read_text(encoding="utf-8")


def test_release_manifest_rejects_unbound_verification_commands(
    tmp_path: Path, fake_gh: Path
) -> None:
    environment, home, fixture, _, _ = _case(tmp_path, fake_gh)
    release_path = fixture / "release-manifest.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release["requires"]["verification_commands"] = []
    release_path.write_bytes(_json_bytes(release))

    result = _run_fallback(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / ".agents" / "skills").exists()
    assert not (_state_root(home) / "active-transaction.json").exists()


@pytest.mark.parametrize("attack", ["duplicate-key", "unknown-field", "bool-as-int"])
@pytest.mark.parametrize("host", POWERSHELLS)
def test_strict_session_manifest_rejects_noncanonical_json(
    tmp_path: Path, fake_gh: Path, host: str, attack: str
) -> None:
    environment, home, fixture, _, expected = _case(tmp_path, fake_gh)
    manifest = json.loads(bytes(expected["session_manifest_bytes"]).decode("utf-8"))
    if attack == "unknown-field":
        manifest["unexpected"] = "not allowed"
        manifest_bytes = _json_bytes(manifest)
    elif attack == "bool-as-int":
        manifest["schema_version"] = True
        manifest_bytes = _json_bytes(manifest)
    else:
        manifest_bytes = bytes(expected["session_manifest_bytes"]).replace(
            b'"target": "codex"',
            b'"target": "codex",\n  "target": "codex"',
            1,
        )
    payload = "---\nname: ru-writing-style\n---\n\nПиши ясно.\n".encode("utf-8")
    _rewrite_session_asset(fixture, manifest_bytes, payload)

    result = _run_fallback(host, environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "TOOLS_APPLIED_NEXT_SESSION" not in result.stdout
    assert not (home / ".agents" / "skills").exists()
    assert not (_state_root(home) / "active-transaction.json").exists()


@pytest.mark.parametrize("mode", [0o100755, 0o120777], ids=["executable", "symlink"])
def test_zip_rejects_executable_and_symlink_entries(
    tmp_path: Path, fake_gh: Path, mode: int
) -> None:
    environment, home, fixture, _, expected = _case(tmp_path, fake_gh)
    payload = "---\nname: ru-writing-style\n---\n\nПиши ясно.\n".encode("utf-8")
    _rewrite_session_asset(
        fixture,
        bytes(expected["session_manifest_bytes"]),
        payload,
        payload_mode=mode,
    )

    result = _run_fallback(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / ".agents" / "skills").exists()
    assert not (_state_root(home) / "active-transaction.json").exists()


def test_exact_package_baseline_recovers_missing_state(
    tmp_path: Path, fake_gh: Path
) -> None:
    environment, home, _, _, expected = _case(tmp_path, fake_gh)
    destination = home / ".agents" / "skills" / "ru-writing-style"
    destination.mkdir(parents=True)
    payload = "---\nname: ru-writing-style\n---\n\nПиши ясно.\n".encode("utf-8")
    (destination / "SKILL.md").write_bytes(payload)
    baseline = home / ".codex" / "base" / "runtime" / "session-tools-baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_bytes(bytes(expected["session_manifest_bytes"]))

    result = _run_fallback(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination / "SKILL.md").read_bytes() == payload
    state = json.loads((_state_root(home) / "state.json").read_text(encoding="utf-8"))
    assert state["tools"][0]["ownership_marker"] == (
        "session-tools-v1:codex:ru-writing-style"
    )


def test_unmanaged_collision_preserves_user_bytes(
    tmp_path: Path, fake_gh: Path
) -> None:
    environment, home, _, _, _ = _case(tmp_path, fake_gh)
    destination = home / ".agents" / "skills" / "ru-writing-style"
    destination.mkdir(parents=True)
    local = destination / "SKILL.md"
    local.write_text("моя локальная версия\n", encoding="utf-8")

    result = _run_fallback(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert local.read_text(encoding="utf-8") == "моя локальная версия\n"
    assert not (_state_root(home) / "state.json").exists()
    assert "BLOCKED_UNMANAGED_COLLISION" in (
        _state_root(home) / "update.log"
    ).read_text(encoding="utf-8")


def test_result_log_redacts_filesystem_exception_paths(
    tmp_path: Path, fake_gh: Path
) -> None:
    environment, home, _, _, _ = _case(tmp_path, fake_gh)
    transaction_root = _state_root(home) / "transactions" / (
        "12345678-1234-1234-1234-123456789abc"
    )
    transaction_root.parent.mkdir(parents=True)
    transaction_root.write_text("collision\n", encoding="utf-8")

    result = _run_managed(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    log_text = (_state_root(home) / "update.log").read_text(encoding="utf-8")
    reason = json.loads(log_text.splitlines()[-1])["reason"]
    assert str(home) not in reason
    assert "collision" not in reason


def test_tampered_launcher_receipt_blocks_before_network(
    tmp_path: Path, fake_gh: Path
) -> None:
    environment, home, _, log, _ = _case(tmp_path, fake_gh)
    launcher = home / ".llm-foundation" / "bin" / "codex-managed.exe"
    launcher.write_bytes(b"tampered launcher\n")

    result = _run_fallback(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not log.exists()
    assert not (home / ".agents" / "skills").exists()
    assert not (_state_root(home) / "active-transaction.json").exists()


@pytest.mark.parametrize("mode", ["missing-gh", "offline"])
def test_missing_gh_and_offline_fail_open_without_mutation(
    tmp_path: Path, fake_gh: Path, mode: str
) -> None:
    environment, home, _, _, _ = _case(tmp_path, fake_gh)
    if mode == "missing-gh":
        environment["PATH"] = str(tmp_path / "empty-path")
    else:
        environment["FAKE_GH_FAIL_MATCH"] = "release list"

    result = _run_fallback(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / ".agents" / "skills").exists()
    assert not (_state_root(home) / "active-transaction.json").exists()


def test_busy_lock_is_bounded_and_skips_network(
    tmp_path: Path, fake_gh: Path
) -> None:
    host = POWERSHELLS[0]
    environment, home, _, log, _ = _case(tmp_path, fake_gh)
    lock = _state_root(home) / "update.lock"
    lock.parent.mkdir(parents=True)
    ready = tmp_path / "lock-ready"
    holder_script = tmp_path / "hold-lock.ps1"
    holder_script.write_text(
        "param([string]$LockPath,[string]$ReadyPath)\n"
        "$stream=[IO.File]::Open($LockPath,'OpenOrCreate','ReadWrite','None')\n"
        "try{[IO.File]::WriteAllText($ReadyPath,'ready');Start-Sleep -Seconds 15}\n"
        "finally{$stream.Dispose()}\n",
        encoding="utf-8",
    )
    holder = subprocess.Popen(
        [
            host,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(holder_script),
            str(lock),
            str(ready),
        ],
        env=environment,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        started = time.monotonic()
        result = _run_fallback(host, environment)
        elapsed = time.monotonic() - started
    finally:
        holder.terminate()
        holder.wait(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    assert elapsed < 4
    assert not log.exists()
    assert not (home / ".agents" / "skills").exists()
    assert "SKIPPED_LOCK_BUSY" in (_state_root(home) / "update.log").read_text(
        encoding="utf-8"
    )


def test_past_mutation_cutoff_skips_network_and_filesystem_mutation(
    tmp_path: Path, fake_gh: Path
) -> None:
    environment, home, _, log, _ = _case(tmp_path, fake_gh)

    result = _run_managed(
        POWERSHELLS[0], environment, start_offset_seconds=-23
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not log.exists()
    assert not (home / ".agents" / "skills").exists()
    assert not (_state_root(home) / "active-transaction.json").exists()


def test_malformed_clock_contract_is_nonzero_before_state_creation(
    tmp_path: Path, fake_gh: Path
) -> None:
    environment, home, _, log, _ = _case(tmp_path, fake_gh)
    start, mutation, kill, deadline, frequency = _stopwatch_contract()
    result = subprocess.run(
        [
            POWERSHELLS[0],
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(UPDATER),
            "-ManagedPreflight",
            "-TransactionId",
            "NOT-A-GUID",
            "-StartTick",
            str(start),
            "-MutationCutoffTick",
            str(mutation),
            "-KillTick",
            str(kill),
            "-HardDeadlineTick",
            str(deadline),
            "-StopwatchFrequency",
            str(frequency),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=10,
    )
    assert result.returncode != 0
    assert not log.exists()
    assert not _state_root(home).exists()


def _journal(
    home: Path,
    receipt: Path,
    *,
    phase: str,
    previous_destination_sha256: str,
    previous_state_sha256: str,
    expected_staging_sha256: str,
    expected_destination_sha256: str,
    expected_state_sha256: str,
    operations: dict[str, dict[str, bool]],
) -> tuple[Path, Path, Path, Path, dict[str, object]]:
    start, mutation, kill, deadline, frequency = _stopwatch_contract()
    transaction_id = "12345678-1234-1234-1234-123456789abc"
    root = _state_root(home)
    transaction = root / "transactions" / transaction_id
    staging = transaction / "staging"
    previous = transaction / "previous"
    destination = home / ".agents" / "skills" / "ru-writing-style"
    state = root / "state.json"
    value: dict[str, object] = {
        "schema_version": 1,
        "target": "codex",
        "transaction_id": transaction_id,
        "phase": phase,
        "receipt_sha256": _sha256_bytes(receipt.read_bytes()),
        "start_tick": start,
        "mutation_cutoff_tick": mutation,
        "kill_tick": kill,
        "hard_deadline_tick": deadline,
        "stopwatch_frequency": frequency,
        "previous_destination_sha256": previous_destination_sha256,
        "previous_state_sha256": previous_state_sha256,
        "expected_staging_sha256": expected_staging_sha256,
        "expected_destination_sha256": expected_destination_sha256,
        "expected_state_sha256": expected_state_sha256,
        "staging_path": str(staging),
        "previous_path": str(previous),
        "destination_path": str(destination),
        "state_path": str(state),
        "operations": operations,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "active-transaction.json").write_bytes(_json_bytes(value))
    return root, staging, previous, destination, value


def _operation_map(enabled: int) -> dict[str, dict[str, bool]]:
    flags = [index < enabled for index in range(6)]
    return {
        "move_destination_to_previous": {
            "intent": flags[0],
            "applied": flags[1],
        },
        "move_staging_to_destination": {
            "intent": flags[2],
            "applied": flags[3],
        },
        "write_state": {"intent": flags[4], "applied": flags[5]},
    }


def test_recovery_reconciles_actual_move_before_network(
    tmp_path: Path, fake_gh: Path
) -> None:
    environment, home, _, log, _ = _case(tmp_path, fake_gh)
    environment["PATH"] = str(tmp_path / "missing-gh")
    receipt = home / ".llm-foundation" / "bin" / "codex-managed.receipt.json"
    destination = home / ".agents" / "skills" / "ru-writing-style"
    previous = _state_root(home) / "transactions" / (
        "12345678-1234-1234-1234-123456789abc"
    ) / "previous"
    destination.mkdir(parents=True)
    previous.mkdir(parents=True)
    (destination / "SKILL.md").write_text("новая версия\n", encoding="utf-8")
    (previous / "SKILL.md").write_text("старая версия\n", encoding="utf-8")
    state = _state_root(home) / "state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("старое состояние\n", encoding="utf-8")
    old_destination = _fingerprint(previous)
    new_destination = _fingerprint(destination)
    old_state = _fingerprint(state)
    root, _, _, _, _ = _journal(
        home,
        receipt,
        phase="move_staging_applied",
        previous_destination_sha256=old_destination,
        previous_state_sha256=old_state,
        expected_staging_sha256=new_destination,
        expected_destination_sha256=new_destination,
        expected_state_sha256="f" * 64,
        operations=_operation_map(4),
    )

    result = _run_fallback(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination / "SKILL.md").read_text(encoding="utf-8") == "старая версия\n"
    assert not previous.exists()
    assert not (root / "active-transaction.json").exists()
    assert not log.exists()


def test_recovery_commits_forward_when_state_write_happened_after_intent(
    tmp_path: Path, fake_gh: Path
) -> None:
    environment, home, _, log, _ = _case(tmp_path, fake_gh)
    environment["PATH"] = str(tmp_path / "missing-gh")
    receipt = home / ".llm-foundation" / "bin" / "codex-managed.receipt.json"
    destination = home / ".agents" / "skills" / "ru-writing-style"
    previous = _state_root(home) / "transactions" / (
        "12345678-1234-1234-1234-123456789abc"
    ) / "previous"
    destination.mkdir(parents=True)
    previous.mkdir(parents=True)
    (destination / "SKILL.md").write_text("новая версия\n", encoding="utf-8")
    (previous / "SKILL.md").write_text("старая версия\n", encoding="utf-8")
    state = _state_root(home) / "state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("новое состояние\n", encoding="utf-8")
    root, _, _, _, _ = _journal(
        home,
        receipt,
        phase="state_write_intent",
        previous_destination_sha256=_fingerprint(previous),
        previous_state_sha256="e" * 64,
        expected_staging_sha256=_fingerprint(destination),
        expected_destination_sha256=_fingerprint(destination),
        expected_state_sha256=_fingerprint(state),
        operations=_operation_map(5),
    )

    result = _run_fallback(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination / "SKILL.md").read_text(encoding="utf-8") == "новая версия\n"
    assert state.read_text(encoding="utf-8") == "новое состояние\n"
    assert not previous.exists()
    assert not (root / "active-transaction.json").exists()
    assert not log.exists()


@pytest.mark.parametrize("phase", ["created", "staged"])
def test_first_install_recovery_cleans_only_transaction_owned_staging(
    tmp_path: Path, fake_gh: Path, phase: str
) -> None:
    environment, home, _, _, _ = _case(tmp_path, fake_gh)
    environment["PATH"] = str(tmp_path / "missing-gh")
    receipt = home / ".llm-foundation" / "bin" / "codex-managed.receipt.json"
    neighbor = _state_root(home) / "transactions" / "neighbor" / "keep.txt"
    neighbor.parent.mkdir(parents=True)
    neighbor.write_text("keep\n", encoding="utf-8")
    staged_hash = "absent"
    if phase == "staged":
        staging = _state_root(home) / "transactions" / (
            "12345678-1234-1234-1234-123456789abc"
        ) / "staging"
        staging.mkdir(parents=True)
        (staging / "SKILL.md").write_text("новая версия\n", encoding="utf-8")
        staged_hash = _fingerprint(staging)
    expected_hash = staged_hash if phase == "staged" else "b" * 64
    root, staging, _, destination, _ = _journal(
        home,
        receipt,
        phase=phase,
        previous_destination_sha256="absent",
        previous_state_sha256="absent",
        expected_staging_sha256=expected_hash,
        expected_destination_sha256=expected_hash,
        expected_state_sha256="a" * 64,
        operations=_operation_map(0),
    )

    result = _run_fallback(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not staging.exists()
    assert not destination.exists()
    assert not (root / "active-transaction.json").exists()
    assert neighbor.read_text(encoding="utf-8") == "keep\n"


def test_created_phase_recovery_removes_safe_partial_staging(
    tmp_path: Path, fake_gh: Path
) -> None:
    environment, home, _, _, _ = _case(tmp_path, fake_gh)
    environment["PATH"] = str(tmp_path / "missing-gh")
    receipt = home / ".llm-foundation" / "bin" / "codex-managed.receipt.json"
    staging = _state_root(home) / "transactions" / (
        "12345678-1234-1234-1234-123456789abc"
    ) / "staging"
    staging.mkdir(parents=True)
    (staging / "partial.txt").write_text("частично\n", encoding="utf-8")
    root, staging, _, destination, _ = _journal(
        home,
        receipt,
        phase="created",
        previous_destination_sha256="absent",
        previous_state_sha256="absent",
        expected_staging_sha256="b" * 64,
        expected_destination_sha256="b" * 64,
        expected_state_sha256="a" * 64,
        operations=_operation_map(0),
    )

    result = _run_fallback(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not staging.exists()
    assert not destination.exists()
    assert not (root / "active-transaction.json").exists()


def test_created_phase_regular_file_staging_blocks_and_preserves_journal(
    tmp_path: Path, fake_gh: Path
) -> None:
    environment, home, _, _, _ = _case(tmp_path, fake_gh)
    environment["PATH"] = str(tmp_path / "missing-gh")
    receipt = home / ".llm-foundation" / "bin" / "codex-managed.receipt.json"
    staging = _state_root(home) / "transactions" / (
        "12345678-1234-1234-1234-123456789abc"
    ) / "staging"
    staging.parent.mkdir(parents=True)
    staging.write_text("не каталог\n", encoding="utf-8")
    root, _, _, destination, _ = _journal(
        home,
        receipt,
        phase="created",
        previous_destination_sha256="absent",
        previous_state_sha256="absent",
        expected_staging_sha256="b" * 64,
        expected_destination_sha256="b" * 64,
        expected_state_sha256="a" * 64,
        operations=_operation_map(0),
    )

    result = _run_fallback(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert staging.read_text(encoding="utf-8") == "не каталог\n"
    assert not destination.exists()
    assert (root / "active-transaction.json").exists()
    assert "BLOCKED_SESSION_RECOVERY" in (root / "update.log").read_text(
        encoding="utf-8"
    )


def test_created_cleanup_is_directory_only_and_rechecks_tree() -> None:
    source = UPDATER.read_text(encoding="utf-8")
    start = source.index("function Remove-SafeCreatedStaging")
    end = source.index("\nfunction ", start + 1)
    helper = source[start:end]

    assert "[IO.File]::Exists($Path)" in helper
    assert "[IO.Directory]::Exists($Path)" in helper
    assert helper.count("Get-SafeTreeFiles $Path") >= 2
    assert "Remove-Item -LiteralPath $Path -Recurse -Force" in helper
    assert "Remove-SafeCreatedStaging" in source[source.index("function Invoke-JournalRecovery") :]


def test_created_phase_nested_reparse_blocks_and_preserves_journal(
    tmp_path: Path, fake_gh: Path
) -> None:
    environment, home, _, _, _ = _case(tmp_path, fake_gh)
    environment["PATH"] = str(tmp_path / "missing-gh")
    receipt = home / ".llm-foundation" / "bin" / "codex-managed.receipt.json"
    staging = _state_root(home) / "transactions" / (
        "12345678-1234-1234-1234-123456789abc"
    ) / "staging"
    staging.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "keep.txt"
    protected.write_text("keep\n", encoding="utf-8")
    link = staging / "nested-link"
    linked = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if linked.returncode != 0:
        pytest.skip("directory junction creation is unavailable")
    root, _, _, _, _ = _journal(
        home,
        receipt,
        phase="created",
        previous_destination_sha256="absent",
        previous_state_sha256="absent",
        expected_staging_sha256="b" * 64,
        expected_destination_sha256="b" * 64,
        expected_state_sha256="a" * 64,
        operations=_operation_map(0),
    )

    result = _run_fallback(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "active-transaction.json").exists()
    assert link.exists()
    assert protected.read_text(encoding="utf-8") == "keep\n"
    assert "BLOCKED_SESSION_RECOVERY" in (root / "update.log").read_text(
        encoding="utf-8"
    )


def test_unknown_journal_operation_blocks_without_cleanup(
    tmp_path: Path, fake_gh: Path
) -> None:
    environment, home, _, _, _ = _case(tmp_path, fake_gh)
    environment["PATH"] = str(tmp_path / "missing-gh")
    receipt = home / ".llm-foundation" / "bin" / "codex-managed.receipt.json"
    operations = _operation_map(0)
    operations["unexpected"] = {"intent": False, "applied": False}
    root, staging, _, _, _ = _journal(
        home,
        receipt,
        phase="created",
        previous_destination_sha256="absent",
        previous_state_sha256="absent",
        expected_staging_sha256="absent",
        expected_destination_sha256="absent",
        expected_state_sha256="a" * 64,
        operations=operations,
    )
    staging.mkdir(parents=True)
    marker = staging / "do-not-delete.txt"
    marker.write_text("keep\n", encoding="utf-8")

    result = _run_fallback(POWERSHELLS[0], environment)

    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text(encoding="utf-8") == "keep\n"
    assert (root / "active-transaction.json").exists()
    assert "BLOCKED_SESSION_RECOVERY" in (root / "update.log").read_text(
        encoding="utf-8"
    )


def test_direct_hook_runs_updater_first_and_emits_one_json_notice(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    shutil.copytree(REPOSITORY_ROOT / "runtime", runtime)
    base_home = tmp_path / "base"
    base_home.mkdir()
    (base_home / "VERSION").write_text("0.1.3\n", encoding="utf-8")
    release_fixture = tmp_path / "releases.json"
    release_fixture.write_text(
        json.dumps(
            [
                {
                    "tag_name": "codex-v0.1.4",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "2026-08-10T00:00:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )
    marker = tmp_path / "updater-ran"
    stub = runtime / "update-session-tools.ps1"
    stub.write_text(
        "param([switch]$HookFallback)\n"
        "[IO.File]::WriteAllText($env:HOOK_TEST_MARKER,'yes')\n"
        "'TOOLS_APPLIED_NEXT_SESSION'\n"
        "'TOOLS_APPLIED_NEXT_SESSION'\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["USERPROFILE"] = str(tmp_path / "home")
    environment["HOOK_TEST_MARKER"] = str(marker)
    environment["CODEX_BASE_HOME_OVERRIDE"] = str(base_home)
    environment["CODEX_BASE_RELEASE_FIXTURE"] = str(release_fixture)

    result = subprocess.run(
        [
            POWERSHELLS[0],
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(runtime / "hooks" / "check_release.ps1"),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text(encoding="utf-8") == "yes"
    lines = [line for line in result.stdout.splitlines() if line]
    assert len(lines) == 1
    message = json.loads(lines[0])["systemMessage"]
    assert "TOOLS_APPLIED_NEXT_SESSION" in message
    assert "Codex-base 0.1.4 is available" in message
    release_state = json.loads(
        (base_home / "state" / "update-check.json").read_text(encoding="utf-8")
    )
    assert release_state["latest_tag"] == "codex-v0.1.4"
    hooks = json.loads((REPOSITORY_ROOT / "runtime" / "hooks.json").read_text())
    hook = hooks["hooks"]["SessionStart"][0]["hooks"][0]
    assert hook["timeout"] >= 35
    assert "next session" in hooks["description"].lower()
