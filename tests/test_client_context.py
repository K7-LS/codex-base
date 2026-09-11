"""Offline tests: only synthetic configs, inert subprocesses, no user profile."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tomllib

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "control-skills/sync-base/client-context.py"
SPEC = importlib.util.spec_from_file_location("client_context", SCRIPT)
context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context)
SECRET = "K7_SENTINEL_SECRET_MUST_NEVER_APPEAR"
windows_only = pytest.mark.skipif(os.name != "nt", reason="native Windows configuration mutation")


def config(tmp_path, payload=b'model = "gpt-6-astra"\nmodel_reasoning_effort = "ultra"\n'):
    path = tmp_path / "config.toml"
    path.write_bytes(payload)
    return path


def own_backups(directory):
    return [item for item in directory.glob("*.bak") if "-displaced-" not in item.name]


@windows_only
@pytest.mark.parametrize("payload", [
    b"", b"# comment", b"[features]\nmemories = true\n",
    b'\xef\xbb\xbfmodel = "gpt-6-astra"\r\n# last comment\r\n',
    b"[features.context_management]\n# keep comment\n",
    b"[features.context_management] # last comment",
    b"[ features . context_management ]\nexperimental_mode  =  false # keep\n",
    b"[features.context_management]\nexperimental_mode = false\nfuture_option = 'keep'\n",
    b"value = nan\nnegative = -nan\nwhen = 2026-09-10T09:20:00Z\n",
    b'''[mcp_servers.private]\nurl = 'https://example.invalid/secret'\n[other]\ntext = """\n[features.context_management]\nexperimental_mode = false\n"""\nvalues = [\n  {secret = '[features]'},\n]\n''',
    b'''text = ''' + b"'''" + b'''literal "quote"\n[features.context_management]\n''' + b"''''" + b"\n",
])
def test_enable_preserves_unrelated_values_and_bytes(tmp_path, payload):
    path = config(tmp_path, payload)
    planned = context.plan(path, True)
    assert path.read_bytes() == payload
    assert planned["changed"] is True
    result = context.apply(path, planned["expected_sha256"], True)
    changed = path.read_bytes()
    context.validate_change(payload, changed, True)
    assert result["next_step"] == "NEW_TASK_REQUIRED"
    assert result["function_behavior"] == "NOT_VERIFIED"
    if payload.startswith(b"\xef\xbb\xbf"):
        assert changed.startswith(b"\xef\xbb\xbf")
        assert b"\n" not in changed.replace(b"\r\n", b"")
    if b"experimental_mode  =  false # keep" in payload:
        assert changed == payload.replace(b"false # keep", b"true # keep")
    assert context.apply(path, context.sha(changed), True)["status"] == "UNCHANGED"
    assert len(own_backups(tmp_path)) == 1
    assert Path(result["displaced_backup"]).read_bytes() == payload
    assert context.rollback(path, Path(result["backup_receipt"]))["status"] == "ROLLED_BACK"
    assert path.read_bytes() == payload
    assert context.rollback(path, Path(result["backup_receipt"]))["status"] == "ALREADY_RESTORED"


@windows_only
@pytest.mark.parametrize("payload", [
    b"[features.context_management]\nexperimental_mode = true\n",
    b"[features.context_management]\nexperimental_mode = false\n",
    b"[features]\nmemories = true\n",
])
def test_disable_and_idempotence(tmp_path, payload):
    path = config(tmp_path, payload)
    result = context.apply(path, context.sha(payload), False)
    changed = path.read_bytes()
    if b"experimental_mode = true" in payload:
        assert result["status"] == "APPLIED"
        assert changed == payload.replace(b"true", b"false")
    else:
        assert result["status"] == "UNCHANGED"
        assert not list(tmp_path.glob("*.bak"))


@pytest.mark.parametrize("payload,reason", [
    (b"features = { memories = true }\n", "INLINE_OR_DOTTED_CONTEXT_UNSUPPORTED"),
    (b"features = { context_management = {experimental_mode = false} }\n", "INLINE_OR_DOTTED_CONTEXT_UNSUPPORTED"),
    (b"[features]\ncontext_management.experimental_mode = false\n", "DOTTED_OR_QUOTED_CONTEXT_UNSUPPORTED"),
    (b"features.context_management.experimental_mode = false\n", "DOTTED_OR_QUOTED_CONTEXT_UNSUPPORTED"),
    (b'["features".context_management]\nexperimental_mode = false\n', "NONSTANDARD_CONTEXT_TABLE"),
    (b"[features.'context_management']\nexperimental_mode = false\n", "NONSTANDARD_CONTEXT_TABLE"),
    (b'[features.context_management]\n"experimental_mode" = false\n', "DOTTED_OR_QUOTED_CONTEXT_UNSUPPORTED"),
    (b"[features.context_management.child]\nvalue = false\n", "NONSTANDARD_CONTEXT_TABLE"),
    (b"[[features.context_management]]\nexperimental_mode = false\n", "CONTEXT_TABLE_FORM_REQUIRED"),
    (b"features = true\n", "FEATURES_MUST_BE_TABLE"),
    (b"[features]\ncontext_management = false\n", "CONTEXT_TABLE_FORM_REQUIRED"),
    (b"[features.context_management]\nexperimental_mode = 1\n", "CONTEXT_FLAG_MUST_BE_BOOLEAN"),
    (b"[features.context_management]\nexperimental_mode = 'false'\n", "CONTEXT_FLAG_MUST_BE_BOOLEAN"),
    (b"[features.context_management]\nexperimental_mode = false\nexperimental_mode = true\n", "INVALID_UTF8_TOML"),
    (b"[features]\ncontext_management = {}\n[features.context_management]\n", "INVALID_UTF8_TOML"),
    (b"key = '\xff'", "INVALID_UTF8_TOML"),
])
def test_unsupported_forms_never_write(tmp_path, payload, reason):
    path = config(tmp_path, payload)
    actions = [lambda: context.plan(path, True)]
    if os.name == "nt":
        actions.append(lambda: context.apply(path, context.sha(payload), True))
    for action in actions:
        with pytest.raises(context.ReviewRequired, match="^" + reason + "$"):
            action()
        assert path.read_bytes() == payload
        assert list(tmp_path.iterdir()) == [path]


def test_inspect_allowlist_no_secret_and_no_subprocess(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(context.subprocess, "run", lambda *a, **k: pytest.fail("implicit process"))
    payload = ('model = "gpt-6-astra"\nmodel_reasoning_effort = "ultra"\n'
               'model_context_window = 272000\nmodel_auto_compact_token_limit = 250000\n'
               '[features]\nmemories = true\n[features.context_management]\nexperimental_mode = true\n'
               '[mcp_servers.private]\nurl = "' + SECRET + '"\n[env]\nTOKEN = "' + SECRET + '"\n').encode()
    path = config(tmp_path, payload)
    assert context.main(["inspect", "--config", str(path)]) == 0
    output = capsys.readouterr().out
    assert SECRET not in output and "mcp_servers" not in output and "TOKEN" not in output
    result = json.loads(output)
    assert result["fields"]["model_reasoning_effort"]["value"] == "ultra"
    assert result["fields"]["features.memories"]["value"] is True
    assert result["sha256"] == context.sha(payload)
    assert path.read_bytes() == payload


def test_invalid_config_error_redacts_values(tmp_path, capsys):
    path = config(tmp_path, ('private = ' + SECRET).encode())
    assert context.main(["plan", "--config", str(path), "--enable"]) == 2
    output = capsys.readouterr().out
    assert SECRET not in output
    assert json.loads(output)["reason"] == "INVALID_UTF8_TOML"


def test_inspect_wrong_allowlisted_types_does_not_expose_nested_secrets(tmp_path):
    path = config(tmp_path, ('model = { secret = "' + SECRET + '" }\nmodel_context_window = true\n').encode())
    result = context.inspect_config(path)
    assert SECRET not in json.dumps(result)
    assert result["fields"]["model_context_window"]["status"] == "UNSUPPORTED_TYPE"


@windows_only
def test_expected_hash_and_drift_before_replace(tmp_path, monkeypatch):
    path = config(tmp_path)
    before = path.read_bytes()
    with pytest.raises(context.ReviewRequired, match="CONCURRENT_CONFIG_CHANGE"):
        context.apply(path, "0" * 64, True)
    assert list(tmp_path.iterdir()) == [path]
    real_write = context.private_write
    foreign = before + b"# edit by another program\n"

    def drift_on_temp(target, payload, source):
        real_write(target, payload, source)
        if target.suffix == ".tmp":
            path.write_bytes(foreign)

    monkeypatch.setattr(context, "private_write", drift_on_temp)
    with pytest.raises(context.ReviewRequired, match="CONCURRENT_CONFIG_CHANGE"):
        context.apply(path, context.sha(before), True)
    assert path.read_bytes() == foreign
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob("*.lock"))


@windows_only
def test_post_validation_failure_restores_original(tmp_path, monkeypatch):
    path = config(tmp_path)
    before = path.read_bytes()
    real_validate = context.validate_change
    calls = []

    def fail_second(*args):
        calls.append(True)
        if len(calls) == 2:
            raise RuntimeError(SECRET)
        return real_validate(*args)

    monkeypatch.setattr(context, "validate_change", fail_second)
    with pytest.raises(context.ReviewRequired, match="POST_VALIDATION_FAILED_ORIGINAL_RESTORED"):
        context.apply(path, context.sha(before), True)
    assert path.read_bytes() == before
    assert len(own_backups(tmp_path)) == 1


@windows_only
def test_post_write_foreign_edit_is_not_reverted(tmp_path, monkeypatch):
    path = config(tmp_path)
    before = path.read_bytes()
    foreign = before + b"# later edit\n"
    real_replace = context.native_replace

    def drift(target, source, displaced):
        result = real_replace(target, source, displaced)
        Path(target).write_bytes(foreign)
        return result

    monkeypatch.setattr(context, "native_replace", drift)
    with pytest.raises(context.ReviewRequired, match="POST_WRITE_DRIFT_BACKUP_RETAINED"):
        context.apply(path, context.sha(before), True)
    assert path.read_bytes() == foreign


@windows_only
def test_rollback_rejects_later_edit_and_tampered_backup(tmp_path):
    path = config(tmp_path)
    result = context.apply(path, context.sha(path.read_bytes()), True)
    installed = path.read_bytes()
    receipt = Path(result["backup_receipt"])
    path.write_bytes(installed + b"# later\n")
    with pytest.raises(context.ReviewRequired, match="CONCURRENT_CONFIG_CHANGE"):
        context.rollback(path, receipt)
    path.write_bytes(installed)
    backup = own_backups(tmp_path)[0]
    backup.write_bytes(b"different = true\n")
    with pytest.raises(context.ReviewRequired, match="OWN_BACKUP_REQUIRED"):
        context.rollback(path, receipt)
    assert path.read_bytes() == installed


@windows_only
def test_rollback_receipt_cannot_target_arbitrary_file(tmp_path):
    path = config(tmp_path)
    result = context.apply(path, context.sha(path.read_bytes()), True)
    receipt = Path(result["backup_receipt"])
    metadata = json.loads(receipt.read_bytes())
    metadata["backup"] = "../secret.toml"
    receipt.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(context.ReviewRequired, match="OWN_BACKUP_REQUIRED"):
        context.rollback(path, receipt)


@windows_only
def test_readonly_is_not_replaced(tmp_path):
    path = config(tmp_path)
    before = path.read_bytes()
    path.chmod(stat.S_IREAD)
    try:
        with pytest.raises(context.ReviewRequired, match="READ_ONLY_CONFIG"):
            context.apply(path, context.sha(before), True)
        assert path.read_bytes() == before
        assert list(tmp_path.iterdir()) == [path]
    finally:
        path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_symlink_file_and_parent_are_rejected(tmp_path):
    original_dir = tmp_path / "original"
    original_dir.mkdir()
    path = config(original_dir)
    link = tmp_path / "link.toml"
    directory_link = tmp_path / "linked-directory"
    try:
        link.symlink_to(path)
        directory_link.symlink_to(original_dir, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit symlink creation; reparse guard still unit tested")
    for item in (link, directory_link / path.name):
        with pytest.raises(context.ReviewRequired, match="SYMLINK_OR_REPARSE_POINT"):
            context.plan(item, True)


def test_reparse_point_guard_with_inert_lstat(tmp_path, monkeypatch):
    path = config(tmp_path)
    real_lstat = Path.lstat

    def lstat(item):
        original = real_lstat(item)
        if item == path:
            class Reparse:
                st_mode = original.st_mode
                st_file_attributes = 0x400
            return Reparse()
        return original

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(context.ReviewRequired, match="SYMLINK_OR_REPARSE_POINT"):
        context.inspect_config(path)


@windows_only
def test_hardlink_rejected(tmp_path):
    path = config(tmp_path)
    os.link(path, tmp_path / "hardlink.toml")
    with pytest.raises(context.ReviewRequired, match="REGULAR_SINGLE_LINK_FILE_REQUIRED"):
        context.apply(path, context.sha(path.read_bytes()), True)


@windows_only
def test_existing_lock_prevents_mutation(tmp_path):
    path = config(tmp_path)
    lock = tmp_path / ".config.toml.client-context.lock"
    lock.write_bytes(b"other invocation")
    with pytest.raises(context.ReviewRequired, match="CONFIG_LOCK_EXISTS"):
        context.apply(path, context.sha(path.read_bytes()), True)
    assert lock.read_bytes() == b"other invocation"


@pytest.mark.parametrize("mode,expected", [
    ("recognized", "RECOGNIZED"), ("unknown-exit-zero", "NOT_VERIFIED"),
    ("always-false", "NOT_VERIFIED"), ("failed", "NOT_VERIFIED"),
    ("duplicate", "NOT_VERIFIED"), ("timeout", "NOT_VERIFIED"),
])
def test_cli_probe_isolation_recognition_and_redaction(tmp_path, monkeypatch, mode, expected):
    executable = tmp_path / "inert-cli.exe"
    executable.write_bytes(b"not executed")
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setenv("HTTPS_PROXY", SECRET)
    monkeypatch.setenv("CODEX_HOME", SECRET)
    roots = []

    def fake_run(command, **kwargs):
        assert command == [str(executable), "features", "list"]
        env = kwargs["env"]
        assert SECRET not in json.dumps(env)
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["timeout"] == 20
        root = Path(env["CODEX_HOME"])
        roots.append(root.parent)
        sample = tomllib.loads((root / "config.toml").read_text())
        value = sample["features"]["context_management"]["experimental_mode"]
        assert not (root / "auth.json").exists()
        assert sample == {"features": {"context_management": {"experimental_mode": value}}}
        if mode == "timeout":
            raise subprocess.TimeoutExpired(command, 20, output=SECRET)
        output = "context_management under development " + str(value if mode != "always-false" else False).lower() + "\n"
        if mode == "unknown-exit-zero":
            output = "unknown " + SECRET
        if mode == "duplicate":
            output *= 2
        return subprocess.CompletedProcess(command, 1 if mode == "failed" else 0,
                                           (output + "private " + SECRET).encode(), SECRET.encode())

    monkeypatch.setattr(context.subprocess, "run", fake_run)
    result = context.probe_cli(executable)
    assert result["context_flag_support"] == expected
    assert result["function_behavior"] == "NOT_VERIFIED"
    assert result["sha256"] == context.sha(b"not executed")
    assert SECRET not in json.dumps(result)
    assert len(roots) == 2 and roots[0] != roots[1]
    assert not any(root.exists() for root in roots)


def test_cli_requires_config_and_expected_hash(tmp_path):
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "apply", "--enable"],
                            capture_output=True, cwd=tmp_path)
    assert result.returncode == 2
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("protected", [False, True])
def test_windows_permission_copy_retains_dacl(tmp_path, protected):
    if os.name != "nt":
        pytest.skip("Windows DACL check")
    import ctypes
    from ctypes import wintypes
    path = config(tmp_path)
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
                                    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]

    def descriptor(item):
        needed = wintypes.DWORD()
        api.GetFileSecurityW(str(item), 7, None, 0, ctypes.byref(needed))
        buffer = ctypes.create_string_buffer(needed.value)
        assert api.GetFileSecurityW(str(item), 7, buffer, needed.value, ctypes.byref(needed))
        return buffer.raw

    def semantic_descriptor(item):
        value = bytearray(descriptor(item))
        control = int.from_bytes(value[2:4], "little")
        # ReplaceFileW may mark automatic inheritance as already propagated;
        # that bookkeeping bit does not grant access or change protection.
        value[2:4] = (control & ~0x0400).to_bytes(2, "little")
        if not control & 0x1000:
            # On unprotected files ReplaceFileW also normalizes ACE provenance.
            # Retain ACE count/type/order/SID/masks and every other flag, plus
            # owner/group and the distinction between NULL and empty DACLs.
            offset = int.from_bytes(value[16:20], "little")
            if offset:
                count = int.from_bytes(value[offset + 4:offset + 6], "little")
                position = offset + 8
                for _ in range(count):
                    value[position + 1] &= ~0x10
                    position += int.from_bytes(value[position + 2:position + 4], "little")
        return bytes(value)

    if protected:
        original = descriptor(path)
        buffer = ctypes.create_string_buffer(original)
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        api.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                                                ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
        assert api.GetSecurityDescriptorDacl(buffer, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted))
        api.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
                                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        assert api.SetNamedSecurityInfoW(str(path), 1, 4 | 0x80000000, None, None, dacl, None) == 0
        assert int.from_bytes(descriptor(path)[2:4], "little") & 0x1000
    before = semantic_descriptor(path)
    result = context.apply(path, context.sha(path.read_bytes()), True)
    assert semantic_descriptor(path) == before
    assert semantic_descriptor(Path(result["backup_receipt"])) == before
    assert all(semantic_descriptor(item) == before for item in tmp_path.glob("*.bak"))


@windows_only
@pytest.mark.parametrize("action", ["apply", "rollback"])
def test_native_last_instant_write_is_retained_as_conflict(tmp_path, monkeypatch, capsys, action):
    path = config(tmp_path)
    before = path.read_bytes()
    receipt = None
    if action == "rollback":
        receipt = context.apply(path, context.sha(before), True)["backup_receipt"]
    expected = context.sha(path.read_bytes())
    foreign = path.read_bytes() + ('\n# ' + SECRET + '\n').encode()
    native = context.native_replace

    def last_instant_edit(target, temporary, displaced):
        # The final require_hash already completed. Execute the real Windows
        # replacement after this synthetic external writer closes the file.
        target.write_bytes(foreign)
        return native(target, temporary, displaced)

    monkeypatch.setattr(context, "native_replace", last_instant_edit)
    arguments = [action, "--config", str(path)]
    arguments += ["--enable", "--expected-sha256", expected] if action == "apply" else ["--receipt", receipt]
    assert context.main(arguments) == 2
    output = capsys.readouterr().out
    assert SECRET not in output
    result = json.loads(output)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["reason"] == "CONCURRENT_REPLACE_CONFLICT"
    captured = next(item for item in result["recovery"]["files"] if item["role"] == "displaced_config")
    assert captured["sha256"] == context.sha(foreign)
    assert Path(captured["path"]).read_bytes() == foreign
    assert path.read_bytes() != foreign  # Conflict is explicit; no blind second overwrite.
    if action == "apply":
        prepared = next(tmp_path.glob("*.json"))
        assert json.loads(prepared.read_bytes())["status"] == "PREPARED"
        with pytest.raises(context.ReviewRequired, match="OWN_BACKUP_REQUIRED"):
            context.rollback(path, prepared)


@windows_only
@pytest.mark.parametrize("error", [1175, 1176, 1177])
def test_partial_native_failure_keeps_recovery_files(tmp_path, monkeypatch, capsys, error):
    path = config(tmp_path)
    before = path.read_bytes()

    def failed_replace(target, temporary, displaced):
        if error == 1177:
            os.replace(target, displaced)
        return error

    monkeypatch.setattr(context, "native_replace", failed_replace)
    assert context.main(["apply", "--config", str(path), "--enable", "--expected-sha256", context.sha(before)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["reason"] == "REPLACE_FAILED_RECOVERY_REQUIRED"
    assert result["recovery"]["win32_error"] == error
    files = {item["role"]: item for item in result["recovery"]["files"]}
    assert Path(files["candidate"]["path"]).is_file()
    if error == 1177:
        assert files["current_config"]["status"] == "ABSENT"
        assert Path(files["displaced_config"]["path"]).read_bytes() == before
    else:
        assert path.read_bytes() == before
    assert json.loads(next(tmp_path.glob("*.json")).read_bytes())["status"] == "PREPARED"


def test_nonwindows_refuses_mutation_without_writes(tmp_path, monkeypatch):
    path = config(tmp_path)
    monkeypatch.setattr(context.os, "name", "posix")
    for action in (lambda: context.apply(path, context.sha(path.read_bytes()), True),
                   lambda: context.rollback(path, tmp_path / "unread.json")):
        with pytest.raises(context.ReviewRequired, match="MUTATION_REQUIRES_WINDOWS_REPLACEFILE"):
            action()
    assert list(tmp_path.iterdir()) == [path]
