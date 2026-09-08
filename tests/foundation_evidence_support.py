"""Synthetic unit fixtures only. These never attest a real engine or model run."""
import json
from pathlib import Path
import zipfile

from codex_base.core_acceptance import body_sha256, json_bytes, sha256
from codex_base.foundation_evidence import ENGINE_FILES, PROTOCOL, SCENARIOS, SHELLS, SOURCE_COMPONENTS, SELECTED_TEST_FILES


def fake_engine_files(version):
    files = {name: b"Synthetic unit-test file; never execute.\n" for name in ENGINE_FILES}
    files["foundation.ps1"] = b"exit 0\n"
    files["VERSION"] = (version + "\n").encode()
    files["engine-manifest.json"] = json_bytes({
        "schema_version": 1, "protocol_version": 1, "engine_version": version,
        "network": "offline", "commands": ["apply", "doctor", "install", "inventory", "plan", "rollback"],
        "supported_powershell": ["5.1", "7"], "foundation_ps1_sha256": sha256(files["foundation.ps1"]),
    })
    files["shared-tools.lock.json"] = json_bytes({"schema_version": 1, "tools": [], "unit_test_only": True})
    return files


def write_fake_engine(root: Path, version="0.1.0"):
    for name, payload in fake_engine_files(version).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return root


def synthetic_foundation(binding, package):
    with zipfile.ZipFile(package) as archive:
        prefix = f".codex/base/foundation/{binding['foundation_engine_version']}/"
        files = {name[len(prefix):]: sha256(archive.read(name)) for name in archive.namelist() if name.startswith(prefix)}
    artifacts = {}
    def artifact(path, raw):
        digest = sha256(raw)
        artifacts[digest] = {"sha256": digest, "bytes": len(raw), "text": raw.decode("utf-8")}
        return {"path": path, "sha256": digest, "bytes": len(raw)}
    command = {"command": ["synthetic-unit-test-only"], "returncode": 0, "stdout": "synthetic", "stderr": ""}
    selected = sorted(SELECTED_TEST_FILES)
    ids = [f"{selected[index]}::test_{shell}_{scenario}" for shell in sorted(SHELLS) for index, scenario in enumerate(sorted(SCENARIOS))]
    xml = ('<testsuites><testsuite tests="14" failures="0" errors="0" skipped="0">'
           + ''.join(f'<testcase classname="{i.split("::")[0][:-3].replace("/", ".")}" name="{i.split("::")[1]}"/>' for i in ids) + '</testsuite></testsuites>').encode()
    junit = artifact("synthetic-results/junit.xml", xml)
    env = {name: "e"*64 for name in ("PATH", "OFFICECLI_NO_AUTO_INSTALL", "OFFICECLI_SKIP_UPDATE")}
    evidence = {
        "schema_version": 1, "acceptance_protocol": PROTOCOL, "unit_test_only": True,
        "engine_version": binding["foundation_engine_version"], "model_requests": 0,
        "real_user_environment_before": env.copy(), "real_user_environment_after": env.copy(),
        "FOUNDATION_ENGINE_ACCEPTANCE": "PASS", "FOUNDATION_SYNTHETIC": "NOT_RUN", "INSTALLER_ACCEPTANCE": "NOT_RUN",
        "historical_not_run_reason": "Synthetic unit fixture only; never an acceptance run.",
        "source": {"repository": "https://github.com/K7-LS/llm-foundation-installer", "commit": "a"*40, "tree": "b"*40,
                   "hashes": {key: "c"*64 for key in SOURCE_COMPONENTS}},
        "scope": {"fake_homes_only": True, "real_consumer_executed": False, "gui_executed": False, "model_requests": 0},
        "powershell_syntax": {shell: {**command, "status": "PASS"} for shell in SHELLS},
        "engine_builds": {shell: {**command, "status": "PASS", "files": files} for shell in SHELLS},
        "deterministic_engine_bundle": "PASS",
        "pytest": {"status": "PASS", "returncode": 0, "selected_files": selected,
                   "selected_files_sha256": {name: "d"*64 for name in selected}, "collected_case_ids": ids,
                   "collection": {**command, "status": "PASS", "command": ["synthetic-unit-test-only", "--collect-only"], "stdout": "\n".join(ids)},
                   "junit_sha256": junit["sha256"], "junit_artifact": junit,
                   "counts": {"tests": 14, "failures": 0, "errors": 0, "skipped": 0}},
        "engine_lifecycle": {"status": "PASS", "evaluation_mode": "SYNTHETIC_HOME",
                             "required_scenarios": sorted(SCENARIOS), "shells": {}},
    }
    for shell in sorted(SHELLS):
        row = {"status": "PASS", "engine_sha256": files["foundation.ps1"], "engine_manifest_sha256": files["engine-manifest.json"],
               "scenario_ids": sorted(SCENARIOS), "user_environment_unchanged": True, "installed_files_verified": True,
               "rollback_byte_identical": True, "receipts": []}
        for scenario in sorted(SCENARIOS):
            env = {name: "e"*64 for name in ("PATH", "OFFICECLI_NO_AUTO_INSTALL", "OFFICECLI_SKIP_UPDATE")}
            receipt = {"scenario_id": scenario, "shell": shell, "status": "PASS", "engine_sha256": files["foundation.ps1"],
                       "engine_manifest_sha256": files["engine-manifest.json"], "commands": [command],
                       "real_user_environment_before": env, "real_user_environment_after": env, "unit_test_only": True}
            receipt["before"] = {"files": {".codex/AGENTS.md": "f"*64}, "fake_environment": env.copy()}
            receipt["after"] = {"files": {".codex/AGENTS.md": "f"*64}, "fake_environment": env.copy()}
            if scenario == "fresh_install_rollback":
                receipt["before"] = {"files": {}, "fake_environment": {}}
                receipt["after"] = {"files": {}, "fake_environment": {}}
            row["receipts"].append(artifact(f"synthetic-results/{shell}-{scenario}.json", json_bytes(receipt)))
        evidence["engine_lifecycle"]["shells"][shell] = row
    evidence["evidence_body_sha256"] = body_sha256(evidence)
    return {"foundation": evidence, "foundation_artifacts": artifacts}
