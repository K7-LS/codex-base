"""Migration trust-boundary tests. All generated releases are synthetic fixtures."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest


SHELLS = [p for name in ("pwsh", "powershell.exe") if (p := shutil.which(name))]
REPO = Path(__file__).resolve().parents[1]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ps_quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def fixture(tmp_path: Path, *, installed="0.1.27", client="0.153.1", inner_fault=""):
    distribution = tmp_path / "distribution"
    distribution.mkdir()
    shutil.copyfile(REPO / "migration/migrate-sync-base.ps1", distribution / "migrate-sync-base.ps1")
    runtime = (REPO / "runtime/connection.ps1").read_bytes().replace(b"\r\n", b"\n")
    (distribution / "connection.ps1").write_bytes(runtime)
    assets = tmp_path / "fixture-assets"
    assets.mkdir()
    home = tmp_path / "synthetic-home"
    home.mkdir()
    (home / "preserved.txt").write_text("unchanged", encoding="utf-8")
    # This tiny verifier only tests orchestration. It is NOT acceptance evidence.
    verifier = b'''param($PolicyPath, $TargetHome, [switch]$LibraryMode)
function Assert-LlmReleaseFiles { param($Directory, $Tag)
    Add-Content -LiteralPath (Join-Path $Directory 'validator-called.txt') -Value $Tag
    return [pscustomobject]@{asset_path=(Join-Path $Directory 'codex-base-0.2.2.zip'); foundation_path='synthetic'; client_id='codex-cli'; client_version='0.153.1'}
}
function Get-LlmInstalledReleaseVersion { return '0.1.27' }
function Get-LlmClientVersion { return '0.153.1' }
function Invoke-LlmFoundationCommand { param($Verified,$Command,$ClientVersion)
    $plan = [pscustomobject]@{status='READY';target='codex';release_version='0.2.2';
        client=@{id='codex-cli';supported_version='0.153.1'};
        package_path=$Verified.asset_path;target_home=$TargetHome;
        package_sha256=$script:MigrationAssetPins.PSObject.Properties['codex-base-0.2.2.zip'].Value.sha256}
    return [pscustomobject]@{exit_code=0;output=("KEEP`n" + ($plan | ConvertTo-Json -Compress))}
}
function Invoke-LlmVerifiedWorkflow { param($Verified,$ClientVersion)
    $planResult = Invoke-LlmFoundationCommand -Verified $Verified -Command plan -ClientVersion $ClientVersion
    if ($planResult.exit_code -ne 0) { throw 'Synthetic plan failed' }
    $null = $planResult.output | ConvertFrom-Json -ErrorAction Stop
    Set-Content -LiteralPath (Join-Path $TargetHome 'installed-marker.txt') -Value 'synthetic installation'
}
'''
    verifier = verifier.replace(b"return '0.1.27'", f"return '{installed}'".encode())
    verifier = verifier.replace(b"return '0.153.1'", f"return '{client}'".encode())
    if inner_fault == "acceptance":
        verifier = verifier.replace(b"param($Directory, $Tag)", b"param($Directory, $Tag)\n throw 'Synthetic acceptance failure'")
    if inner_fault == "plan_noise":
        verifier = verifier.replace(b'KEEP`n', b'unexpected`n')
    if inner_fault == "plan_binding":
        verifier = verifier.replace(b"target='codex'", b"target='claude'")
    if inner_fault == "plan_exit":
        verifier = verifier.replace(b"exit_code=0", b"exit_code=7")
    embedded = {
        ".agents/skills/sync-base/tools/sync_base.ps1": verifier,
        ".agents/skills/sync-base/sync-policy.json": b'{"synthetic":true}',
    }
    package = {
        "target": "codex", "version": "0.2.2",
        "files": [{"path": name, "sha256": digest(data), "bytes": len(data)}
                  for name, data in embedded.items()],
    }
    package_bytes = json.dumps(package).encode()
    with zipfile.ZipFile(assets / "codex-base-0.2.2.zip", "w") as archive:
        for name, data in embedded.items():
            if inner_fault == "updater_digest" and name.endswith("sync_base.ps1"):
                data += b"\n# tampered"
            archive.writestr(name, data)
        if inner_fault == "duplicate_entry":
            name = ".agents/skills/sync-base/tools/sync_base.ps1"
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr(name, embedded[name])
        archive.writestr("package-manifest.json", package_bytes)
    manifest = {
        "target": "codex", "version": "0.2.2", "tag": "codex-v0.2.2", "channel": "stable",
        "package_manifest_sha256": digest(package_bytes),
    }
    if inner_fault == "package_digest":
        manifest["package_manifest_sha256"] = "0" * 64
    if inner_fault == "target":
        manifest["target"] = "opencode"
    (assets / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (assets / "components.lock.json").write_text("{}", encoding="utf-8")
    (assets / "acceptance-evidence.json").write_text("{}", encoding="utf-8")
    (assets / "session-tools-codex-0.2.2.zip").write_bytes(b"synthetic session tools")
    pins = {p.name: {"sha256": digest(p.read_bytes()), "bytes": p.stat().st_size}
            for p in assets.iterdir()}
    pins_path = tmp_path / "synthetic-pins.json"
    pins_path.write_text(json.dumps(pins), encoding="utf-8")
    return distribution, assets, home, pins_path


def run_probe(tmp_path, shell, *, mode="Verify", failure="", release_change=None, corrupt=False,
              extra=False, post_setup="", installed="0.1.27", client="0.153.1", inner_fault="", path_form=""):
    distribution, assets, home, pins_path = fixture(tmp_path, installed=installed, client=client, inner_fault=inner_fault)
    if corrupt:
        with (assets / "acceptance-evidence.json").open("ab") as stream:
            stream.write(b"tamper")
    if extra:
        (assets / "unexpected.ps1").write_text("throw 'must not execute'", encoding="utf-8")
    releases = [{"tagName": "codex-v0.2.2", "isDraft": False, "isPrerelease": False, "isImmutable": True},
                {"tagName": "codex-v0.1.27", "isDraft": False, "isPrerelease": False, "isImmutable": True},
                {"tagName": "sync-base-migration-v1.0.0", "isDraft": False, "isPrerelease": False, "isImmutable": True},
                {"tagName": "codex-v9.0.0", "isDraft": False, "isPrerelease": True, "isImmutable": True},
                {"tagName": "codex-v0.2.0", "isDraft": False, "isPrerelease": False, "isImmutable": True}]
    if release_change:
        releases[0].update(release_change)
    release_path = tmp_path / "releases.json"
    release_path.write_text(json.dumps(releases), encoding="utf-8")
    work = tmp_path / "work"
    work_argument = str(work)
    if path_form in {"extended", "junction"}:
        (home / ".codex").mkdir()
        if path_form == "extended":
            work_argument = "\\\\?\\" + str(home / ".codex/fresh")
        else:
            alias = tmp_path / "alias"
            post_setup += f"\nNew-Item -ItemType Junction -Path {ps_quote(alias)} -Target {ps_quote(home)} | Out-Null"
            work_argument = str(alias / ".codex/fresh")
    elif path_form == "trailing_dot":
        work_argument += "."
    trace = tmp_path / "gh-trace.txt"
    command = f"""
$ErrorActionPreference = 'Stop'
. {ps_quote(distribution / 'migrate-sync-base.ps1')} -LibraryMode
# Test-only replacement of pins and GitHub transport for synthetic bytes.
$script:MigrationAssetPins = Get-Content -LiteralPath {ps_quote(pins_path)} -Raw | ConvertFrom-Json
function Invoke-MigrationGh {{
    param([string[]]$Arguments)
    $operation = ($Arguments[0..1] -join ' ')
    if ($Arguments -notcontains 'K7-LS/codex-base') {{ throw 'Wrong repository boundary' }}
    Add-Content -LiteralPath {ps_quote(trace)} -Value $operation
    if ($operation -ceq {ps_quote(failure)}) {{ throw 'Synthetic GitHub failure' }}
    if ($operation -ceq 'release list') {{ return (Get-Content -LiteralPath {ps_quote(release_path)} -Raw) }}
    if ($operation -ceq 'release download') {{
        $destination = $Arguments[[array]::IndexOf($Arguments, '--dir') + 1]
        Get-ChildItem -LiteralPath {ps_quote(assets)} -File | Copy-Item -Destination $destination
    }}
    return '{{}}'
}}
{post_setup}
Invoke-SyncMigration -WorkDirectory {ps_quote(work_argument)} -TargetHome {ps_quote(home)} -Mode {ps_quote(mode)}
"""
    probe = tmp_path / "probe.ps1"
    probe.write_text(command, encoding="utf-8-sig")
    result = subprocess.run([shell, "-NoProfile", "-File", str(probe)], capture_output=True, timeout=60)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    return result.returncode, output, work, home, trace


@pytest.mark.parametrize("shell", SHELLS)
def test_default_verification_preserves_profile_and_verifies_before_loading(tmp_path, shell):
    code, output, work, home, trace = run_probe(tmp_path, shell)
    assert code == 0, output
    assert '"VERIFIED"' in output
    assert sorted(p.name for p in home.iterdir()) == ["preserved.txt"]
    assert (home / "preserved.txt").read_text() == "unchanged"
    assert (work / "assets/validator-called.txt").exists()
    calls = trace.read_text().splitlines()
    assert calls[:3] == ["release list", "release verify", "release download"]
    assert calls[3:] == ["release verify-asset", "attestation verify"] * 5


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("mode", ["Plan", "Install"])
def test_explicit_modes_call_verified_workflow_only(tmp_path, shell, mode):
    code, output, _, home, _ = run_probe(tmp_path, shell, mode=mode)
    assert code == 0, output
    assert (home / "installed-marker.txt").exists() is (mode == "Install")
    assert (home / "preserved.txt").read_text() == "unchanged"
    if mode == "Plan":
        assert json.loads(output)["status"] == "READY"


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("failure", ["release verify", "release verify-asset", "attestation verify"])
def test_signature_failure_stops_before_extraction_or_install(tmp_path, shell, failure):
    code, _, work, home, _ = run_probe(tmp_path, shell, mode="Install", failure=failure)
    assert code != 0
    assert not (work / "updater").exists()
    assert not (home / "installed-marker.txt").exists()


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("change", [{"isDraft": True}, {"isPrerelease": True},
                                    {"isImmutable": False}, {"tagName": "codex-v0.2.3"}])
def test_only_pinned_latest_immutable_stable_is_allowed(tmp_path, shell, change):
    code, _, work, home, trace = run_probe(tmp_path, shell, release_change=change)
    assert code != 0
    assert trace.read_text().splitlines() == ["release list"]
    assert not (work / "updater").exists()
    assert not (home / "installed-marker.txt").exists()


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("mutation", ["corrupt", "extra"])
def test_asset_set_and_pins_fail_closed(tmp_path, shell, mutation):
    code, _, work, home, _ = run_probe(tmp_path, shell, **{mutation: True})
    assert code != 0
    assert not (work / "updater").exists()
    assert not (home / "installed-marker.txt").exists()


@pytest.mark.parametrize("shell", SHELLS)
def test_invalid_work_directory_does_not_overwrite(tmp_path, shell):
    sentinel = tmp_path / "work/sentinel.txt"
    sentinel.parent.mkdir()
    sentinel.write_text("keep", encoding="utf-8")
    code, _, _, home, trace = run_probe(tmp_path, shell)
    assert code != 0
    assert sentinel.read_text() == "keep"
    assert not trace.exists()
    assert not (home / "installed-marker.txt").exists()


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("fault", ["package_digest", "updater_digest", "duplicate_entry", "target", "acceptance",
                                   "plan_noise", "plan_binding", "plan_exit"])
def test_inner_binding_or_acceptance_failure_never_installs(tmp_path, shell, fault):
    code, _, _, home, _ = run_probe(tmp_path, shell, mode="Install", inner_fault=fault)
    assert code != 0
    assert sorted(p.name for p in home.iterdir()) == ["preserved.txt"]


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("mode", ["Plan", "Install"])
@pytest.mark.parametrize("mismatch", [{"installed": "0.3.0"}, {"installed": ""}, {"client": "0.153.0"}])
def test_state_and_actual_client_requirements_fail_closed(tmp_path, shell, mode, mismatch):
    code, _, _, home, _ = run_probe(tmp_path, shell, mode=mode, **mismatch)
    assert code != 0
    assert sorted(p.name for p in home.iterdir()) == ["preserved.txt"]


@pytest.mark.parametrize("shell", SHELLS)
def test_equal_version_is_a_no_op(tmp_path, shell):
    code, output, _, home, _ = run_probe(tmp_path, shell, mode="Install", installed="0.2.2")
    assert code == 0, output
    assert '"ALREADY_CURRENT"' in output
    assert sorted(p.name for p in home.iterdir()) == ["preserved.txt"]


@pytest.mark.parametrize("shell", SHELLS)
def test_runtime_tamper_stops_before_network(tmp_path, shell):
    command = "[IO.File]::AppendAllText($script:MigrationRuntime, '# tampered')"
    code, _, _, home, trace = run_probe(tmp_path, shell, post_setup=command)
    assert code != 0
    assert not trace.exists()
    assert sorted(p.name for p in home.iterdir()) == ["preserved.txt"]


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("path_form", ["extended", "junction", "trailing_dot"])
def test_profile_alias_and_windows_path_normalization_cannot_bypass_staging_guard(tmp_path, shell, path_form):
    code, _, _, home, trace = run_probe(tmp_path, shell, path_form=path_form)
    assert code != 0
    assert not (home / ".codex/fresh").exists()
    assert not trace.exists()
    assert (home / "preserved.txt").read_text() == "unchanged"


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("native_exit", [0, 1])
def test_native_stderr_is_not_a_failure_or_a_secret_leak(tmp_path, shell, native_exit):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "gh.cmd").write_text(
        f"@echo off\necho {{}}\necho synthetic-proxy-secret 1>&2\nexit /b {native_exit}\n", encoding="ascii")
    script = tmp_path / "native.ps1"
    script.write_text(f"""
$ErrorActionPreference = 'Stop'
. {ps_quote(REPO / 'migration/migrate-sync-base.ps1')} -LibraryMode
$env:PATH = {ps_quote(fake_bin)} + ';' + $env:PATH
try {{ Invoke-MigrationGh -Arguments @('release','verify') | Out-Null; Write-Output 'SUCCESS' }}
catch {{ [Console]::Error.WriteLine($_.Exception.Message); exit 2 }}
""", encoding="utf-8-sig")
    result = subprocess.run([shell, "-NoProfile", "-File", str(script)], capture_output=True, timeout=60)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert (result.returncode == 0) is (native_exit == 0), output
    assert "synthetic-proxy-secret" not in output


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("mutation", ["clean", "echo", "noise", "two_plans", "after_plan", "missing",
                                     "target", "version", "client", "hash", "package", "home", "blocked", "tampered_file",
                                     "duplicate_status", "duplicate_client", "escaped_duplicate", "duplicate_case",
                                     "root_array", "nested_valid", "key_words", "array_status", "array_target",
                                     "array_release_version", "array_package_sha256", "array_package_path", "array_target_home",
                                     "array_client_id", "array_client_version", "array_client"])
def test_plan_adapter_preserves_one_bound_plan_and_rejects_ambiguity(tmp_path, shell, mutation):
    home = tmp_path / "home"
    home.mkdir()
    package = tmp_path / "package.zip"
    package.write_bytes(b"synthetic package already verified by the previous stage")
    package_hash = digest(package.read_bytes())
    plan = {"status": "READY", "target": "codex", "release_version": "0.2.2",
            "client": {"id": "codex-cli", "supported_version": "0.153.1"},
            "package_sha256": package_hash,
            "package_path": str(package), "target_home": str(home)}
    changes = {"target": ("target", "claude"), "version": ("release_version", "0.2.0"),
               "hash": ("package_sha256", "0" * 64), "package": ("package_path", str(tmp_path / "other.zip")),
               "home": ("target_home", str(tmp_path / "other-home")), "blocked": ("status", "BLOCKED_USER_DECISION")}
    if mutation in changes:
        key, value = changes[mutation]
        plan[key] = value
    if mutation == "client":
        plan["client"]["supported_version"] = "0.153.0"
    if mutation == "tampered_file":
        package.write_bytes(b"replaced after validation")
    if mutation == "nested_valid":
        plan["actions"] = [{"path": "a", "status": "unchanged"}, {"path": "b", "status": "write"}]
    if mutation == "key_words":
        plan["note"] = 'KEEP\n{"status":"BLOCKED"}: REMOVE'
    if mutation == "array_client_id":
        plan["client"]["id"] = ["codex-cli", "codex-cli"]
    elif mutation == "array_client_version":
        plan["client"]["supported_version"] = ["0.153.1", "0.153.1"]
    elif mutation.startswith("array_"):
        key = mutation.removeprefix("array_")
        plan[key] = [plan[key], plan[key]]
    line = json.dumps(plan, separators=(",", ":"))
    payload = {"echo": "KEEP\nremove\n" + line, "noise": "untrusted noise\n" + line,
               "two_plans": line + "\n" + line, "after_plan": line + "\nKEEP",
               "missing": "KEEP\n", "root_array": "[" + line + "]",
               "duplicate_status": '{"status":"BLOCKED",' + line[1:],
               "duplicate_case": '{"STATUS":"READY",' + line[1:],
               "escaped_duplicate": r'{"sta\u0074us":"BLOCKED",' + line[1:],
               "duplicate_client": line.replace('"id":"codex-cli"', '"id":"wrong","id":"codex-cli"')}.get(mutation, line)
    raw = tmp_path / "plan.stdout"
    raw.write_text(payload, encoding="utf-8")
    script = tmp_path / "plan.ps1"
    script.write_text(f"""
$ErrorActionPreference = 'Stop'
. {ps_quote(REPO / 'migration/migrate-sync-base.ps1')} -LibraryMode
$script:MigrationAssetPins.PSObject.Properties['codex-base-0.2.2.zip'].Value.sha256 = {ps_quote(package_hash)}
$verified = [pscustomobject]@{{asset_path={ps_quote(package)}}}
Convert-MigrationPlanOutput -Output (Get-Content -LiteralPath {ps_quote(raw)} -Raw -Encoding UTF8) -Verified $verified -ExpectedHome {ps_quote(home)}
""", encoding="utf-8-sig")
    result = subprocess.run([shell, "-NoProfile", "-File", str(script)], capture_output=True, timeout=60)
    if mutation in {"clean", "echo", "nested_valid", "key_words"}:
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        assert result.stdout.decode("utf-8").strip() == line
    else:
        assert result.returncode != 0


def load_builder():
    spec = importlib.util.spec_from_file_location("migration_builder", REPO / "tools/build_sync_migration.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_distribution_is_deterministic_and_truthfully_records_source(tmp_path):
    builder = load_builder()
    first = builder.build(tmp_path / "first")
    second = builder.build(tmp_path / "second")
    assert first["asset"] == second["asset"]
    assert first["status"] == "CANDIDATE_UNPUBLISHED"
    assert first["base_package_rebuilt"] is False
    assert isinstance(first["source"]["worktree_dirty"], bool)
    assert first["base_release"] == "codex-v0.2.2"
    with zipfile.ZipFile(tmp_path / "first" / first["asset"]["name"]) as archive:
        assert sorted(archive.namelist()) == ["README.md", "connection.ps1", "migrate-sync-base.ps1"]
        for row in first["files"]:
            content = archive.read(row["path"])
            assert len(content) == row["bytes"]
            assert digest(content) == row["sha256"]
    with pytest.raises(ValueError, match="already exists"):
        builder.build(tmp_path / "first")


def test_builder_rejects_changed_bundled_runtime_before_creating_output(tmp_path):
    source = tmp_path / "source"
    (source / "migration").mkdir(parents=True)
    (source / "runtime").mkdir()
    for name in ("migrate-sync-base.ps1", "README.md"):
        shutil.copyfile(REPO / "migration" / name, source / "migration" / name)
    (source / "runtime/connection.ps1").write_bytes(b"unexpected code")
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="runtime differs"):
        load_builder().build(output, root=source)
    assert not output.exists()


@pytest.mark.parametrize("dirty", [False, True])
def test_publication_assets_require_committed_clean_source(tmp_path, dirty):
    source = tmp_path / "source"
    (source / "migration").mkdir(parents=True)
    (source / "runtime").mkdir()
    for relative in ("migration/migrate-sync-base.ps1", "migration/README.md", "runtime/connection.ps1"):
        shutil.copyfile(REPO / relative, source / relative)
    subprocess.run(["git", "init", "-q"], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Migration fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-qm", "Synthetic release source"],
                   cwd=source, check=True, capture_output=True)
    if dirty:
        with (source / "migration/README.md").open("ab") as stream:
            stream.write(b"\nUncommitted fixture change\n")
    output = tmp_path / "release"
    if dirty:
        with pytest.raises(ValueError, match="clean committed source"):
            load_builder().build(output, root=source, for_publication=True)
        assert not output.exists()
    else:
        manifest = load_builder().build(output, root=source, for_publication=True)
        assert manifest["status"] == "RELEASE_PREPARED"
        assert manifest["source"]["worktree_dirty"] is False
        assert manifest["source"]["commit"] == subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
        assert manifest["base_package_rebuilt"] is False
