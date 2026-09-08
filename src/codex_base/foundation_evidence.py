"""Package-bound engine evidence; distinct from historical full installer tests."""
from __future__ import annotations

from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from .core_acceptance import body_sha256, read_json, sha256, validate_current_wire_keys

PROTOCOL = "foundation-engine-isolated-v1"
SHELLS = {"ps7", "ps51"}
SCENARIOS = {
    "fresh_install_rollback", "existing_install_rollback", "late_failure_rollback",
    "interrupted_recovery", "snapshot_tamper_rejected", "receipt_drift_rejected",
    "foreign_generation_rejected",
}
ENGINE_FILES = {
    "VERSION", "engine-manifest.json", "foundation.ps1", "shared-tools.lock.json",
    "shared-tools/officecli/officecli.exe", "shared-tools/officecli/officecli-shim.exe",
    "shared-tools/officecli/officecli-command-policy.json",
    "shared-tools/officecli/k7-officecli-pdf.exe",
    "shared-tools/officecli/officecli_csv_batch.py",
}
SOURCE_COMPONENTS = {"VERSION", "APP_VERSION", "client-sources.lock.json", "src", "tests", "tools"}
SELECTED_TEST_FILES = {
    "tests/test_foundation.py", "tests/test_foundation_shared_tools.py",
    "tests/test_foundation_release.py", "tests/test_acceptance_runner.py",
    "tests/test_professional_core_compat.py", "tests/test_engine_isolated_lifecycle.py",
    "tests/test_engine_acceptance_runner.py",
}
USER_ENVIRONMENT = {"path", "officecli_no_auto_install", "officecli_skip_update"}
MAX_TEXT_BYTES = 4 * 1024 * 1024


def _need(condition, message):
    if not condition:
        raise ValueError("Foundation engine evidence: " + message)


def _sha(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _map(value, label):
    _need(isinstance(value, dict), label + " must be an object")
    return value


def _hash_map(value, keys, label):
    _map(value, label)
    _need(set(value) == set(keys) and all(_sha(v) for v in value.values()), label + " differs")


def _user_environment_unchanged(value, label):
    before = _map(value.get("real_user_environment_before"), label + " User environment before")
    _need({k.casefold() for k in before} == USER_ENVIRONMENT and len(before) == 3
          and all(_sha(v) for v in before.values()) and value.get("real_user_environment_after") == before,
          label + " real User environment changed or unverified")


def _junit_identity(node_id):
    file, _, address = node_id.partition("::")
    method, bracket, parameters = address.partition("[")
    parts = method.split("::")
    classname = ".".join([file.removesuffix(".py").replace("/", "."), *parts[:-1]])
    return classname, parts[-1] + bracket + parameters


def _engine_identity(version_bytes, manifest_bytes, files, version):
    _need(version_bytes.decode("utf-8").strip() == version, "actual engine VERSION differs")
    manifest = _map(read_json(manifest_bytes), "actual engine manifest")
    _need(manifest.get("engine_version") == version
          and manifest.get("foundation_ps1_sha256") == files["foundation.ps1"],
          "actual engine manifest identity differs")


def _command(value, label, *, passed=False):
    _map(value, label)
    _need(isinstance(value.get("command"), list) and value["command"]
          and all(isinstance(v, str) and v for v in value["command"]), label + " command missing")
    _need(_integer(value.get("returncode")), label + " return code missing")
    _need(all(isinstance(value.get(k), str) for k in ("stdout", "stderr")), label + " output missing")
    if passed:
        _need(value.get("status") == "PASS" and value["returncode"] == 0, label + " did not pass")


def _artifact(record, artifacts):
    _map(record, "artifact reference")
    digest = record.get("sha256")
    _need(_sha(digest) and _integer(record.get("bytes")) and record["bytes"] > 0, "artifact reference invalid")
    _need(isinstance(record.get("path"), str) and bool(record["path"]), "artifact origin missing")
    item = _map(artifacts.get(digest), "artifact payload")
    _need(isinstance(item.get("text"), str), "artifact UTF-8 text missing")
    raw = item["text"].encode("utf-8")
    _need(len(raw) == record["bytes"] == item.get("bytes") and sha256(raw) == digest == item.get("sha256"),
          "artifact bytes differ")
    return raw


def _references(evidence):
    yield evidence["pytest"]["junit_artifact"]
    for shell in sorted(SHELLS):
        yield from evidence["engine_lifecycle"]["shells"][shell]["receipts"]


def collect_foundation_artifacts(evidence: dict, root: Path) -> dict:
    """Read only declared text proofs beneath the supplied evidence directory."""
    root = root.resolve(strict=True)
    result = {}
    total = 0
    for record in _references(evidence):
        path = Path(record["path"])
        if not path.is_absolute():
            path = root / path
        _need(path.resolve().is_relative_to(root), "artifact escapes evidence directory")
        current = path
        while current != root:
            metadata = current.lstat()
            _need(not current.is_symlink() and not (getattr(metadata, "st_file_attributes", 0) & 0x400),
                  "artifact contains reparse point")
            current = current.parent
        _need(path.is_file() and 0 < path.stat().st_size <= MAX_TEXT_BYTES, "artifact size invalid")
        raw = path.read_bytes()
        digest = sha256(raw)
        _need(digest == record["sha256"] and len(raw) == record["bytes"], "artifact changed")
        if digest not in result:
            total += len(raw)
            _need(total <= MAX_TEXT_BYTES, "proof bundle exceeds size limit")
            result[digest] = {"sha256": digest, "bytes": len(raw), "text": raw.decode("utf-8")}
    return result


def validate_foundation_engine(evidence: dict, artifacts: dict, binding: dict,
                               *, engine_root: Path | None = None, package_path: Path | None = None) -> dict:
    """Validate source/build/lifecycle claims and their actual packaged engine bytes.

    Preserved raw test outputs establish reviewability, not execution authenticity.
    The producer's independent execution review remains necessary.
    """
    _map(evidence, "evidence")
    _map(artifacts, "artifacts")
    validate_current_wire_keys(evidence)
    validate_current_wire_keys(artifacts)
    _need(_integer(evidence.get("schema_version")) and evidence["schema_version"] == 1 and evidence.get("acceptance_protocol") == PROTOCOL,
          "protocol missing or unknown")
    _need(evidence.get("FOUNDATION_ENGINE_ACCEPTANCE") == "PASS", "engine gate did not pass")
    _need(evidence.get("FOUNDATION_SYNTHETIC") == "NOT_RUN" and evidence.get("INSTALLER_ACCEPTANCE") == "NOT_RUN",
          "engine-only scope must preserve unrun installer gates")
    _need(isinstance(evidence.get("historical_not_run_reason"), str) and evidence["historical_not_run_reason"].strip(),
          "historical scope reason missing")
    _need(evidence.get("evidence_body_sha256") == body_sha256(evidence), "body hash differs")
    _need(evidence.get("engine_version") == binding.get("foundation_engine_version"), "engine version differs")
    _user_environment_unchanged(evidence, "overall run")
    _need(_integer(evidence.get("model_requests")) and evidence["model_requests"] == 0, "unexpected model requests")
    scope = _map(evidence.get("scope"), "scope")
    _need(scope.get("fake_homes_only") is True and scope.get("real_consumer_executed") is False
          and scope.get("gui_executed") is False and _integer(scope.get("model_requests"))
          and scope["model_requests"] == 0, "scope differs")
    source = _map(evidence.get("source"), "source")
    _need(source.get("repository") == "https://github.com/K7-LS/llm-foundation-installer", "source repository differs")
    _need(all(isinstance(source.get(k), str) and re.fullmatch("[0-9a-f]{40}", source[k]) for k in ("commit", "tree")),
          "committed source identity missing")
    _hash_map(source.get("hashes"), SOURCE_COMPONENTS, "source component hashes")
    builds = _map(evidence.get("engine_builds"), "engine builds")
    syntax = _map(evidence.get("powershell_syntax"), "PowerShell syntax")
    _need(set(builds) == set(syntax) == SHELLS, "both PowerShell versions are required")
    _need(evidence.get("deterministic_engine_bundle") == "PASS", "build determinism did not pass")
    files = _map(builds["ps7"], "PowerShell 7 build").get("files")
    _hash_map(files, ENGINE_FILES, "built engine inventory")
    _need(files["engine-manifest.json"] == binding.get("foundation_engine_manifest_sha256"), "engine manifest binding differs")
    for shell in SHELLS:
        _command(syntax[shell], shell + " syntax", passed=True)
        _command(builds[shell], shell + " build", passed=True)
        _need(builds[shell].get("files") == files, "PowerShell builds differ")
    if engine_root is not None:
        paths = [engine_root, *engine_root.rglob("*")]
        for path in paths:
            metadata = path.lstat()
            _need(not path.is_symlink() and not (getattr(metadata, "st_file_attributes", 0) & 0x400),
                  "engine contains reparse point")
        actual = {p.relative_to(engine_root).as_posix(): sha256(p.read_bytes()) for p in paths if p.is_file()}
        _need(actual == files, "actual engine files differ")
        _engine_identity((engine_root / "VERSION").read_bytes(), (engine_root / "engine-manifest.json").read_bytes(), files, evidence["engine_version"])
    if package_path is not None:
        prefix = f".codex/base/foundation/{evidence['engine_version']}/"
        with zipfile.ZipFile(package_path) as archive:
            names = [n for n in archive.namelist() if n.startswith(prefix) and not n.endswith("/")]
            _need(len(names) == len(set(names)), "duplicate packaged engine files")
            actual = {n[len(prefix):]: sha256(archive.read(n)) for n in names}
            _need(actual == files, "packaged engine files differ")
            _engine_identity(archive.read(prefix + "VERSION"), archive.read(prefix + "engine-manifest.json"), files, evidence["engine_version"])
    tests = _map(evidence.get("pytest"), "pytest")
    _need(tests.get("status") == "PASS" and _integer(tests.get("returncode")) and tests["returncode"] == 0,
          "selected engine tests did not pass")
    selected = tests.get("selected_files")
    _need(isinstance(selected, list) and all(isinstance(v, str) for v in selected)
          and len(selected) == len(SELECTED_TEST_FILES) and set(selected) == SELECTED_TEST_FILES, "selected engine test contract differs")
    _hash_map(tests.get("selected_files_sha256"), selected, "selected test hashes")
    cases = tests.get("collected_case_ids")
    _need(isinstance(cases, list) and cases and all(isinstance(v, str) and "::" in v and v.split("::")[0] in selected for v in cases)
          and len(cases) == len(set(cases)), "collected tests missing or unbound")
    _need({node.split("::")[0] for node in cases} == set(selected), "selected test file has no collected cases")
    collection = tests.get("collection")
    _command(collection, "test collection", passed=True)
    _need("--collect-only" in collection["command"], "test collection command differs")
    collected_output = [line.strip() for line in collection["stdout"].splitlines()
                        if line.startswith("tests/") and "::" in line]
    _need(collected_output == cases, "actual collected output differs")
    junit = _artifact(tests.get("junit_artifact"), artifacts)
    _need(sha256(junit) == tests.get("junit_sha256"), "JUnit binding differs")
    tree = ET.fromstring(junit)
    _need(tree.tag in {"testsuites", "testsuite"}, "JUnit root differs")
    _need(list(tree.iter("testcase")) and not any(list(tree.iter(k)) for k in ("failure", "error", "skipped")),
          "JUnit contains failure/error/skip or no tests")
    suites = list(tree.iter("testsuite"))
    _need(suites and all(s.get(k) == "0" for s in suites for k in ("failures", "errors", "skipped")),
          "JUnit suite declares failure/error/skip")
    actual_cases = [(case.get("classname"), case.get("name")) for case in tree.iter("testcase")]
    _need(len(actual_cases) == len(cases) and set(actual_cases) == {_junit_identity(node) for node in cases},
          "JUnit identities differ from collected tests")
    counts = _map(tests.get("counts"), "test counts")
    _need(all(_integer(counts.get(k)) and counts[k] == 0 for k in ("failures", "errors", "skipped"))
          and _integer(counts.get("tests")) and counts["tests"] == sum(int(s.get("tests", "0")) for s in tree.iter("testsuite"))
          and counts["tests"] >= len(cases), "JUnit counts differ")
    lifecycle = _map(evidence.get("engine_lifecycle"), "lifecycle")
    _need(lifecycle.get("status") == "PASS" and lifecycle.get("evaluation_mode") == "SYNTHETIC_HOME", "lifecycle not accepted")
    _need(isinstance(lifecycle.get("required_scenarios"), list) and len(lifecycle["required_scenarios"]) == len(SCENARIOS)
          and set(lifecycle["required_scenarios"]) == SCENARIOS, "scenario contract differs")
    shells = _map(lifecycle.get("shells"), "lifecycle shells")
    _need(set(shells) == SHELLS, "lifecycle shell missing")
    for shell, row in shells.items():
        _map(row, "lifecycle shell")
        _need(row.get("status") == "PASS" and row.get("engine_sha256") == files["foundation.ps1"]
              and row.get("engine_manifest_sha256") == files["engine-manifest.json"], "lifecycle engine binding differs")
        _need(all(row.get(k) is True for k in ("user_environment_unchanged", "installed_files_verified", "rollback_byte_identical")),
              "lifecycle invariant did not pass")
        _need(isinstance(row.get("scenario_ids"), list) and len(row["scenario_ids"]) == len(SCENARIOS)
              and set(row["scenario_ids"]) == SCENARIOS, "lifecycle coverage differs")
        receipts = row.get("receipts")
        _need(isinstance(receipts, list) and len(receipts) == len(SCENARIOS), "lifecycle receipts missing")
        seen = set()
        for ref in receipts:
            receipt = _map(read_json(_artifact(ref, artifacts)), "lifecycle receipt")
            scenario = receipt.get("scenario_id")
            _need(scenario in SCENARIOS and scenario not in seen and receipt.get("shell") == shell
                  and receipt.get("status") == "PASS", "lifecycle receipt identity differs")
            seen.add(scenario)
            _need(receipt.get("engine_sha256") == files["foundation.ps1"]
                  and receipt.get("engine_manifest_sha256") == files["engine-manifest.json"], "receipt engine differs")
            commands = receipt.get("commands")
            _need(isinstance(commands, list) and commands, "receipt has no executed command")
            for command in commands:
                _command(command, "lifecycle command")
            _user_environment_unchanged(receipt, "receipt")
            before = _map(receipt.get("before"), "receipt state before")
            _need(set(before) == {"files", "fake_environment"}, "receipt state inventory missing")
            for key in ("files", "fake_environment"):
                values = _map(before.get(key), "receipt " + key)
                _need(all(isinstance(k, str) and k and _sha(v) for k, v in values.items()), "receipt state hash invalid")
            _need(USER_ENVIRONMENT.issubset({k.casefold() for k in before["fake_environment"]})
                  and receipt.get("after") == before, "receipt rollback state differs")
    expected_ids = {ref["sha256"] for ref in _references(evidence)}
    _need(set(artifacts) == expected_ids, "unreferenced or missing engine artifacts")
    _need(sum(len(a["text"].encode("utf-8")) for a in artifacts.values()) <= MAX_TEXT_BYTES, "proof bundle exceeds size limit")
    return {"FOUNDATION_ENGINE_ACCEPTANCE": "PASS", "protocol": PROTOCOL,
            "engine_version": evidence["engine_version"], "lifecycle_cases": len(SCENARIOS) * len(SHELLS)}
