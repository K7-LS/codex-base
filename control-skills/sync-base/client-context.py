#!/usr/bin/env python3
"""Optional, local Codex context diagnostics and one-key configuration changes.

Python 3.11+. Does not install anything or run a model. No user profile is
implicitly selected. JSON errors deliberately omit raw exception/config text.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
import uuid
from contextlib import contextmanager

KEY = ("features", "context_management", "experimental_mode")
OWNER = "k7-client-context-v1"
LIMIT = 4 * 1024 * 1024
UNVERIFIED = {
    "function_behavior": "NOT_VERIFIED",
    "operation_tool_availability": "NOT_VERIFIED",
    "account_experiment_availability": "NOT_VERIFIED",
    "active_desktop_configuration": "NOT_VERIFIED",
}


class ReviewRequired(Exception):
    """Only fixed, non-sensitive reason codes may cross the CLI boundary."""

    def __init__(self, reason, recovery=None):
        super().__init__(reason)
        self.recovery = recovery


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def safe_path(value, *, writable=False):
    path = Path(os.path.abspath(value))
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ReviewRequired("SYMLINK_OR_REPARSE_POINT")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ReviewRequired("REGULAR_SINGLE_LINK_FILE_REQUIRED")
    if writable and (not info.st_mode & stat.S_IWUSR or
                     getattr(info, "st_file_attributes", 0) & 1):
        raise ReviewRequired("READ_ONLY_CONFIG")
    return path


def read_bytes(path):
    if path.stat().st_size > LIMIT:
        raise ReviewRequired("FILE_SIZE_LIMIT")
    with path.open("rb") as handle:
        result = handle.read(LIMIT + 1)
    if len(result) > LIMIT:
        raise ReviewRequired("FILE_SIZE_LIMIT")
    return result


def parse(payload):
    try:
        return tomllib.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise ReviewRequired("INVALID_UTF8_TOML") from None


def lookup(data, keys):
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def inspect_config(path):
    payload = read_bytes(safe_path(path))
    data = parse(payload)
    fields = {}
    allowed = {
        "model": str, "model_reasoning_effort": str,
        "model_context_window": int, "model_auto_compact_token_limit": int,
        "features.memories": bool, "features.context_management": bool,
        "features.context_management.experimental_mode": bool,
    }
    for key, kind in allowed.items():
        value = lookup(data, key.split("."))
        if key == "features.context_management" and isinstance(value, dict):
            fields[key] = {"status": "TABLE"}
        elif value is not None:
            fields[key] = ({"status": "PRESENT", "value": value}
                           if type(value) is kind else {"status": "UNSUPPORTED_TYPE"})
        else:
            fields[key] = {"status": "ABSENT"}
    return {"status": "INSPECTED", "sha256": sha(payload),
            "toml": "VALID", "fields": fields, **UNVERIFIED}


def tokens(text):
    """Lexical spans only. tomllib remains the authoritative TOML parser.

    Strings (including multiline strings), comments and balanced containers
    cannot impersonate assignment keys or table headers.
    """
    i = 0
    while i < len(text):
        start = i
        ch = text[i]
        if ch in " \t\r":
            i += 1
            continue
        if ch == "#":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        if ch in "\"'":
            delimiter = ch * (3 if text.startswith(ch * 3, i) else 1)
            i += len(delimiter)
            while i < len(text):
                if ch == '"' and text[i] == "\\":
                    i += 2
                elif text.startswith(delimiter, i):
                    i += len(delimiter)
                    # TOML permits one/two extra terminal quotes in multiline strings.
                    if len(delimiter) == 3:
                        for _ in range(2):
                            if i < len(text) and text[i] == ch:
                                i += 1
                    break
                else:
                    i += 1
            yield ("string", text[start:i], start, i)
        elif ch in "\n[]{}=.,":
            i += 1
            yield (ch, ch, start, i)
        else:
            while i < len(text) and text[i] not in " \t\r\n[]{}=.,#\"'":
                i += 1
            yield ("bare", text[start:i], start, i)


def statements(text):
    current, depth = [], 0
    for token in tokens(text):
        if token[0] == "\n" and depth == 0:
            if current:
                yield current, token[3]
            current = []
            continue
        current.append(token)
        if token[0] in ("[", "{"):
            depth += 1
        elif token[0] in ("]", "}"):
            depth -= 1
    if current:
        yield current, len(text)


def key_parts(items):
    result, plain = [], True
    for index, token in enumerate(items):
        if index % 2:
            if token[0] != ".":
                raise ReviewRequired("UNSUPPORTED_CONTEXT_SYNTAX")
        elif token[0] == "bare":
            result.append(token[1])
        elif token[0] == "string":
            result.append(tomllib.loads("v = " + token[1])["v"])
            plain = False
        else:
            raise ReviewRequired("UNSUPPORTED_CONTEXT_SYNTAX")
    return tuple(result), plain


def edit_spans(text):
    table, header_end, value_span = (), None, None
    for items, end in statements(text):
        if items[0][0] == "[":
            array = len(items) > 1 and items[1][0] == "["
            table, plain = key_parts(items[2:-2] if array else items[1:-1])
            if table[:1] == KEY[:1] and len(table) == 1 and (array or not plain):
                raise ReviewRequired("NONSTANDARD_FEATURES_TABLE")
            if table[:2] == KEY[:2]:
                if array or not plain or table != KEY[:2]:
                    raise ReviewRequired("NONSTANDARD_CONTEXT_TABLE")
                header_end = end
            continue
        equal = next(i for i, token in enumerate(items) if token[0] == "=")
        parts, plain = key_parts(items[:equal])
        absolute = table + parts
        if absolute in (KEY[:1], KEY[:2]):
            raise ReviewRequired("INLINE_OR_DOTTED_CONTEXT_UNSUPPORTED")
        if absolute[:2] == KEY[:2]:
            if table != KEY[:2] or len(parts) != 1 or not plain:
                raise ReviewRequired("DOTTED_OR_QUOTED_CONTEXT_UNSUPPORTED")
            if absolute == KEY:
                value = items[equal + 1:]
                if len(value) != 1 or value[0][1] not in ("true", "false"):
                    raise ReviewRequired("CONTEXT_FLAG_MUST_BE_BOOLEAN")
                value_span = (value[0][2], value[0][3])
    return header_end, value_span


def same_values(left, right):
    # TOML permits nan, for which ordinary Python equality is false.
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_values(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same_values(a, b) for a, b in zip(left, right))
    if isinstance(left, float) and math.isnan(left) and math.isnan(right):
        return True
    return left == right


def validate_change(before, after, enable):
    original, actual = parse(before), parse(after)
    expected = copy.deepcopy(original)
    expected.setdefault("features", {}).setdefault("context_management", {})[KEY[-1]] = enable
    if not same_values(expected, actual):
        raise ReviewRequired("UNRELATED_VALUES_CHANGED")


def candidate(payload, enable):
    data = parse(payload)
    features = data.get("features", {})
    if not isinstance(features, dict):
        raise ReviewRequired("FEATURES_MUST_BE_TABLE")
    context = features.get("context_management", {})
    if not isinstance(context, dict):
        raise ReviewRequired("CONTEXT_TABLE_FORM_REQUIRED")
    value = context.get(KEY[-1])
    if value is not None and type(value) is not bool:
        raise ReviewRequired("CONTEXT_FLAG_MUST_BE_BOOLEAN")
    text = payload.decode("utf-8-sig")
    header_end, value_span = edit_spans(text)
    if value is enable or (value is None and not enable):
        return payload
    newline = "\r\n" if "\r\n" in text else "\n"
    boolean = "true" if enable else "false"
    if value_span is not None:
        start, end = value_span
        revised = text[:start] + boolean + text[end:]
    elif header_end is not None:
        prefix = "" if text[:header_end].endswith("\n") else newline
        revised = text[:header_end] + prefix + "experimental_mode = " + boolean + newline + text[header_end:]
    else:
        prefix = "" if not text or text.endswith("\n") else newline
        revised = text + prefix + newline + "[features.context_management]" + newline + "experimental_mode = " + boolean + newline
    result = (b"\xef\xbb\xbf" if payload.startswith(b"\xef\xbb\xbf") else b"") + revised.encode("utf-8")
    validate_change(payload, result, enable)
    return result


def plan(path, enable):
    payload = read_bytes(safe_path(path))
    proposed = candidate(payload, enable)
    return {"status": "PLAN", "expected_sha256": sha(payload),
            "proposed_sha256": sha(proposed), "changed": payload != proposed,
            "key": ".".join(KEY), "requested_value": enable,
            "unrelated_values": "PRESERVED", **UNVERIFIED}


def copy_permissions(source, target):
    """Protect empty new files before writing configuration bytes into them."""
    if os.name != "nt":
        os.chmod(target, stat.S_IMODE(source.stat().st_mode))
        return
    from ctypes import wintypes
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    get = api.GetFileSecurityW
    get.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
                    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    get.restype = wintypes.BOOL
    needed = wintypes.DWORD()
    get(str(source), 4, None, 0, ctypes.byref(needed))
    if not needed.value:
        raise ReviewRequired("PERMISSIONS_NOT_PRESERVED")
    buffer = ctypes.create_string_buffer(needed.value)
    if not get(str(source), 4, buffer, needed.value, ctypes.byref(needed)):
        raise ReviewRequired("PERMISSIONS_NOT_PRESERVED")
    control, revision = wintypes.WORD(), wintypes.DWORD()
    api.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
    if not api.GetSecurityDescriptorControl(buffer, ctypes.byref(control), ctypes.byref(revision)):
        raise ReviewRequired("PERMISSIONS_NOT_PRESERVED")
    if not control.value & 0x1000:
        # The new file starts unprotected. Copy the descriptor directly rather
        # than rerunning inheritance and changing explicit ACEs to inherited.
        set_file = api.SetFileSecurityW
        set_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        set_file.restype = wintypes.BOOL
        if not set_file(str(target), 4, buffer):
            raise ReviewRequired("PERMISSIONS_NOT_PRESERVED")
        return
    present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
    api.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                                            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    if not api.GetSecurityDescriptorDacl(buffer, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
        raise ReviewRequired("PERMISSIONS_NOT_PRESERVED")
    set_security = api.SetNamedSecurityInfoW
    set_security.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    set_security.restype = wintypes.DWORD
    if set_security(str(target), 1, 4 | 0x80000000, None, None, dacl, None) != 0:
        raise ReviewRequired("PERMISSIONS_NOT_PRESERVED")


def private_write(path, payload, source):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        copy_permissions(source, path)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def config_lock(path):
    lock = path.with_name("." + path.name + ".client-context.lock")
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ReviewRequired("CONFIG_LOCK_EXISTS") from None
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(OWNER.encode("ascii"))
        yield
    finally:
        lock.unlink()


def require_hash(path, expected):
    payload = read_bytes(safe_path(path, writable=True))
    if sha(payload) != expected:
        raise ReviewRequired("CONCURRENT_CONFIG_CHANGE")
    return payload


def require_windows():
    if os.name != "nt":
        raise ReviewRequired("MUTATION_REQUIRES_WINDOWS_REPLACEFILE")


def native_replace(path, temporary, displaced):
    """Capture the file actually displaced, including a last-instant edit."""
    from ctypes import wintypes
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    replace = api.ReplaceFileW
    replace.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                        wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    replace.restype = wintypes.BOOL
    # No IGNORE_ACL_ERRORS / IGNORE_MERGE_ERRORS: preserve security metadata.
    if not replace(str(path), str(temporary), str(displaced), 0, None, None):
        return ctypes.get_last_error()
    return 0


def recovery_files(path, temporary, displaced):
    result = []
    for role, item in (("current_config", path), ("candidate", temporary), ("displaced_config", displaced)):
        entry = {"role": role, "path": str(item)}
        try:
            entry["sha256"] = sha(read_bytes(safe_path(item)))
        except FileNotFoundError:
            entry["status"] = "ABSENT"
        except Exception:
            entry["status"] = "NOT_READABLE"
        result.append(entry)
    return result


def atomic_write(path, payload, expected):
    require_windows()
    identifier = uuid.uuid4().hex
    temporary = path.with_name("." + path.name + ".client-context-" + identifier + ".tmp")
    displaced = path.with_name("." + path.name + ".client-context-displaced-" + identifier + ".bak")
    attempted = False
    try:
        private_write(temporary, payload, path)
        if read_bytes(temporary) != payload:
            raise ReviewRequired("TEMP_VALIDATION_FAILED")
        require_hash(path, expected)
        attempted = True
        error = native_replace(path, temporary, displaced)
        if error:
            # ReplaceFileW can partially complete (e.g. error 1177). Retain all
            # remaining files, including the candidate; never guess a repair.
            raise ReviewRequired("REPLACE_FAILED_RECOVERY_REQUIRED",
                                 {"win32_error": error, "config_may_have_changed": True,
                                  "automatic_restore": "NOT_ATTEMPTED",
                                  "files": recovery_files(path, temporary, displaced)})
        try:
            captured_hash = sha(read_bytes(safe_path(displaced)))
        except Exception:
            raise ReviewRequired("DISPLACED_FILE_NOT_VERIFIED",
                                 {"config_replaced": True, "automatic_restore": "NOT_ATTEMPTED",
                                  "files": recovery_files(path, temporary, displaced)}) from None
        if captured_hash != expected:
            raise ReviewRequired("CONCURRENT_REPLACE_CONFLICT",
                                 {"config_replaced": True, "automatic_restore": "NOT_ATTEMPTED",
                                  "files": recovery_files(path, temporary, displaced)})
        # Retain even a matching displaced file: another writer may still hold
        # an open handle to it and complete its write after this check.
        return displaced
    finally:
        if not attempted and temporary.exists():
            temporary.unlink()


def update_receipt(receipt, metadata):
    # This metadata file is ours. An interrupted write makes it unusable for
    # automatic rollback, while every configuration backup remains available.
    safe_path(receipt, writable=True)
    with receipt.open("wb") as handle:
        handle.write((json.dumps(metadata, ensure_ascii=True, indent=2) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


def apply(path, expected, enable):
    require_windows()
    path = safe_path(path, writable=True)
    with config_lock(path):
        before = require_hash(path, expected)
        after = candidate(before, enable)
        if before == after:
            return {"status": "UNCHANGED", "sha256": sha(before),
                    "next_step": "NEW_TASK_REQUIRED", **UNVERIFIED}
        operation = uuid.uuid4().hex
        prefix = "." + path.name + ".client-context-" + operation
        backup = path.with_name(prefix + ".bak")
        receipt = path.with_name(prefix + ".json")
        metadata = {"owner": OWNER, "operation": operation, "config": str(path),
                    "backup": backup.name, "before_sha256": sha(before),
                    "after_sha256": sha(after), "requested_value": enable, "status": "PREPARED"}
        private_write(backup, before, path)
        private_write(receipt, (json.dumps(metadata, ensure_ascii=True, indent=2) + "\n").encode("utf-8"), path)
        if read_bytes(backup) != before:
            raise ReviewRequired("BACKUP_VALIDATION_FAILED")
        try:
            displaced = atomic_write(path, after, expected)
        except ReviewRequired as error:
            error.recovery = {**(error.recovery or {}), "backup_receipt": str(receipt)}
            raise
        try:
            current = read_bytes(safe_path(path))
            if current != after:
                raise ReviewRequired("POST_WRITE_DRIFT")
            validate_change(before, current, enable)
        except Exception:
            # Never overwrite an intervening edit, even while recovering a failure.
            if read_bytes(safe_path(path)) == after:
                atomic_write(path, before, sha(after))
                if read_bytes(path) != before:
                    raise ReviewRequired("RESTORE_VALIDATION_FAILED") from None
                raise ReviewRequired("POST_VALIDATION_FAILED_ORIGINAL_RESTORED") from None
            raise ReviewRequired("POST_WRITE_DRIFT_BACKUP_RETAINED",
                                 {"config_may_have_changed": True, "backup_receipt": str(receipt),
                                  "displaced_backup": str(displaced)}) from None
        metadata["status"] = "APPLIED"
        update_receipt(receipt, metadata)
        return {"status": "APPLIED", "sha256": sha(after), "backup_receipt": str(receipt),
                "displaced_backup": str(displaced),
                "next_step": "NEW_TASK_REQUIRED", **UNVERIFIED}


def rollback(path, receipt_path):
    require_windows()
    path = safe_path(path, writable=True)
    receipt = safe_path(receipt_path)
    if receipt.parent != path.parent:
        raise ReviewRequired("OWN_BACKUP_REQUIRED")
    try:
        metadata = json.loads(read_bytes(receipt))
        operation = metadata["operation"]
        if not re.fullmatch(r"[0-9a-f]{32}", operation):
            raise ValueError()
        prefix = "." + path.name + ".client-context-" + operation
        if (metadata["owner"] != OWNER or metadata["config"] != str(path) or
                receipt.name != prefix + ".json" or metadata["backup"] != prefix + ".bak" or
                type(metadata["requested_value"]) is not bool or metadata["status"] not in ("APPLIED", "ROLLED_BACK")):
            raise ValueError()
        backup = safe_path(path.with_name(metadata["backup"]))
        original = read_bytes(backup)
        if sha(original) != metadata["before_sha256"]:
            raise ValueError()
        reconstructed = candidate(original, metadata["requested_value"])
        if sha(reconstructed) != metadata["after_sha256"] or reconstructed == original:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ReviewRequired("OWN_BACKUP_REQUIRED") from None
    with config_lock(path):
        current = read_bytes(safe_path(path, writable=True))
        if current == original:
            return {"status": "ALREADY_RESTORED", "sha256": sha(current), **UNVERIFIED}
        if metadata["status"] != "APPLIED":
            raise ReviewRequired("OWN_BACKUP_REQUIRED")
        require_hash(path, metadata["after_sha256"])
        metadata["status"] = "ROLLBACK_PREPARED"
        update_receipt(receipt, metadata)
        displaced = atomic_write(path, original, metadata["after_sha256"])
        if read_bytes(safe_path(path)) != original:
            raise ReviewRequired("ROLLBACK_POST_WRITE_DRIFT")
        metadata["status"] = "ROLLED_BACK"
        update_receipt(receipt, metadata)
    return {"status": "ROLLED_BACK", "sha256": sha(original),
            "displaced_backup": str(displaced),
            "next_step": "NEW_TASK_REQUIRED", **UNVERIFIED}


def isolated_environment(root):
    # No inherited token, provider, proxy, MCP/plugin or personal PATH values.
    env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "COMSPEC") if key in os.environ}
    for name in ("home", "codex", "appdata", "localappdata", "temp", "config", "cache", "data"):
        (root / name).mkdir()
    env.update(HOME=str(root / "home"), USERPROFILE=str(root / "home"),
               CODEX_HOME=str(root / "codex"), APPDATA=str(root / "appdata"),
               LOCALAPPDATA=str(root / "localappdata"), TMP=str(root / "temp"), TEMP=str(root / "temp"),
               XDG_CONFIG_HOME=str(root / "config"), XDG_CACHE_HOME=str(root / "cache"),
               XDG_DATA_HOME=str(root / "data"), PATH="", NO_COLOR="1")
    return env


def probe_cli(cli):
    # A managed CLI's bin directory may be a version-switching junction.
    # Resolve it once and probe/hash the immutable version path. Config edits
    # deliberately do not resolve links and retain their stricter guard.
    executable = safe_path(Path(cli).resolve(strict=True))
    with executable.open("rb") as handle:
        binary_hash = hashlib.file_digest(handle, "sha256").hexdigest()
    outcomes = []
    for enabled in (False, True):
        with tempfile.TemporaryDirectory(prefix="k7-context-probe-") as directory:
            root = Path(directory)
            env = isolated_environment(root)
            # Both samples are synthetic. The user's config is never copied.
            (root / "codex" / "config.toml").write_text(
                "[features.context_management]\nexperimental_mode = " + str(enabled).lower() + "\n", encoding="utf-8")
            try:
                result = subprocess.run([str(executable), "features", "list"], cwd=root / "home",
                                        env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                        timeout=20, creationflags=0x08000000 if os.name == "nt" else 0)
                observed = []
                for line in result.stdout[:LIMIT].decode("utf-8", errors="replace").splitlines():
                    match = re.fullmatch(r"context_management\s+(stable|experimental|under development|deprecated|removed)\s+(true|false)\s*", line)
                    if match:
                        observed.append({"stage": match[1], "value": match[2] == "true"})
                outcomes.append({"requested_value": enabled, "exit_code": result.returncode,
                                 "observed": observed[0] if len(observed) == 1 else None})
            except (subprocess.TimeoutExpired, OSError):
                outcomes.append({"requested_value": enabled, "status": "PROBE_UNAVAILABLE"})
    with executable.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != binary_hash:
            raise ReviewRequired("CLI_CHANGED_DURING_PROBE")
    supported = all(item.get("exit_code") == 0 and item.get("observed") is not None and
                    item["observed"]["value"] == item["requested_value"] for item in outcomes)
    return {"sha256": binary_hash, "context_flag_support": "RECOGNIZED" if supported else "NOT_VERIFIED",
            "probe": "ISOLATED_FEATURES_LIST", "samples": outcomes, **UNVERIFIED}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "plan", "apply", "rollback"):
        item = commands.add_parser(command)
        item.add_argument("--config", type=Path, required=True)
        if command == "inspect":
            item.add_argument("--cli", type=Path)
        if command in ("plan", "apply"):
            choice = item.add_mutually_exclusive_group(required=True)
            choice.add_argument("--enable", dest="enable", action="store_true")
            choice.add_argument("--disable", dest="enable", action="store_false")
        if command == "apply":
            item.add_argument("--expected-sha256", required=True)
        if command == "rollback":
            item.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "inspect":
            result = inspect_config(arguments.config)
            if arguments.cli is not None:
                result["cli"] = probe_cli(arguments.cli)
        elif arguments.command == "plan":
            result = plan(arguments.config, arguments.enable)
        elif arguments.command == "apply":
            if not re.fullmatch(r"[0-9a-fA-F]{64}", arguments.expected_sha256):
                raise ReviewRequired("SHA256_REQUIRED")
            result = apply(arguments.config, arguments.expected_sha256.lower(), arguments.enable)
        else:
            result = rollback(arguments.config, arguments.receipt)
    except ReviewRequired as error:
        result = {"status": "REVIEW_REQUIRED", "reason": str(error), **UNVERIFIED}
        if error.recovery is not None:
            result["recovery"] = error.recovery
    except Exception:
        # File names, TOML values and process stderr may be sensitive.
        result = {"status": "REVIEW_REQUIRED", "reason": "LOCAL_OPERATION_FAILED", **UNVERIFIED}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 2 if result["status"] == "REVIEW_REQUIRED" else 0


if __name__ == "__main__":
    sys.exit(main())
