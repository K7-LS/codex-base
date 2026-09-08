"""Synthetic unit-test evidence ONLY. Never a live run or release attestation."""

import json
from pathlib import Path
import zipfile

from codex_base.core_acceptance import (
    CLAIM, PACKAGE_CONTRACT_PATH, SUITE_PATH, body_sha256, contract_bytes,
    contract_reference, expected_contract, json_bytes, package_source_inventory,
    sha256, package_client, package_discovery, package_foundation_sha256,
)


def minimal_package(root: Path, binding: dict) -> Path:
    binding.setdefault("foundation_engine_version", "test-foundation")
    entries = {
        ".codex/AGENTS.md": b"Synthetic test instructions\n",
        ".codex/config.toml": b"# Synthetic config\n",
        PACKAGE_CONTRACT_PATH: contract_bytes(),
        f".codex/base/foundation/{binding['foundation_engine_version']}/foundation.ps1": b"exit 0\n",
    }
    manifest = {
        "schema_version": 1, "target": binding["target"], "version": binding["version"],
        "core_behavior_contract": contract_reference(),
        "client": {"id": "codex-cli", "supported_version": "0.146.0-alpha.3.1"},
    }
    entries["package-manifest.json"] = json_bytes(manifest)
    path = root / str(binding["asset"]["name"])
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    binding["asset"].update(sha256=sha256(path.read_bytes()), bytes=path.stat().st_size)
    binding["package_manifest_sha256"] = sha256(entries["package-manifest.json"])
    binding["core_behavior_contract"] = contract_reference()
    return path


def synthetic_core(binding: dict, package: Path, root: Path, *, model="test-model-a", effort="test-effort") -> dict:
    inventory = package_source_inventory(package, binding)
    inventory_hash = sha256(json_bytes(inventory))
    loaded_inventory = {".codex/AGENTS.md": inventory[".codex/AGENTS.md"]}
    loaded_hash = sha256(json_bytes(loaded_inventory))
    evidence = {
        "schema_version": 1, "kind": "core_behavior_evidence", "evaluation_mode": "RELEASE_PACKAGE",
        "protocol": contract_reference(), "release_binding": binding,
        "CORE_BEHAVIOR": "PASS", "claim": CLAIM, "artifacts": {},
        "suite_artifact": "suite", "harness_artifact": "harness", "evaluator_artifact": "evaluator", "runs": [],
    }

    def artifact(key, payload):
        relative = f"core-artifacts/{key}.json"
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        evidence["artifacts"][key] = {"path": relative, "sha256": sha256(payload), "bytes": len(payload)}

    artifact("suite", SUITE_PATH.read_bytes())
    artifact("harness", b"# Synthetic unit-test harness, not live evidence\n")
    artifact("evaluator", b"# Synthetic unit-test reviewer, not live evidence\n")
    artifact("config", b'{"unit_test":true}\n')
    artifact("fixture", b'{"unit_test_fixture":true}\n')
    for case_id, criteria in expected_contract()["criteria"].items():
        case_spec = next(case for case in json.loads(SUITE_PATH.read_bytes())["cases"] if case["id"] == case_id)
        run_id = f"synthetic-{case_id}"
        runtime = {"client": package_client(package),
                   "model": model, "reasoning_effort": effort, "effective_config_artifact": "config"}
        loaded = {"kind": "loaded_source", "run_id": run_id, "runtime": runtime,
                  "source_inventory_sha256": inventory_hash,
                  "loaded_source_inventory_sha256": loaded_hash,
                  "harness_sha256": evidence["artifacts"]["harness"]["sha256"],
                  "fixture_hashes": {"fixture": evidence["artifacts"]["fixture"]["sha256"]}}
        answer = {"kind": "assistant_message", "run_id": run_id, "text": "Synthetic unit-test observation only"}
        submitted = {"kind": "user_message", "run_id": run_id, "case_id": case_id, "text": case_spec["prompt"],
                     "case_spec_sha256": sha256(json_bytes(case_spec)), "fixture_hashes": loaded["fixture_hashes"]}
        event_values = [loaded, submitted, answer]
        if "mid_task_user_message" in case_spec:
            event_values.extend([{"kind": "user_message", "run_id": run_id, "text": case_spec["mid_task_user_message"]}, answer])
        lines = [json.dumps(item, sort_keys=True).encode() for item in event_values]
        events_key = f"{case_id}-events"
        artifact(events_key, b"\n".join(lines) + b"\n")
        pointer = {"artifact": events_key, "line": len(lines), "sha256": sha256(lines[-1])}
        run = {"id": run_id, "case_id": case_id, "status": "PASS", "subject_id": "synthetic-subject",
               "runtime": runtime, "events_artifact": events_key, "materialized_source_inventory": inventory,
               "loaded_source_inventory": loaded_inventory,
               "source_load_event": {"artifact": events_key, "line": 1, "sha256": sha256(lines[0])},
               "input_event": {"artifact": events_key, "line": 2, "sha256": sha256(lines[1])},
               "fixture_artifacts": ["fixture"]}
        if "mid_task_user_message" in case_spec:
            run.update({field: {"artifact": events_key, "line": number, "sha256": sha256(lines[number - 1])}
                        for field, number in (("pre_mid_task_observation", 3), ("mid_task_input_event", 4), ("post_mid_task_observation", 5))})
        statuses = {}
        for group, status in (("must_observe", "PASS"), ("critical_fail", "ABSENT")):
            run[group] = {key: {"status": status, "reason": "Synthetic unit test, not an expert verdict", "evidence": [dict(pointer)]}
                          for key in criteria[group]}
            statuses.update({key: status for key in criteria[group]})
        review_key = f"{case_id}-review"
        artifact(review_key, json_bytes({
            "run_id": run_id, "reviewer_id": "synthetic-independent-reviewer", "independent": True,
            "case_id": case_id, "input_event_sha256": sha256(lines[1]),
            "verdict": "PASS", "criterion_statuses": statuses, "source_inventory_sha256": inventory_hash,
            "loaded_source_inventory_sha256": loaded_hash,
            "events_sha256": evidence["artifacts"][events_key]["sha256"],
            "evaluator_sha256": evidence["artifacts"]["evaluator"]["sha256"],
        }))
        run["review"] = {"reviewer_id": "synthetic-independent-reviewer", "independent": True, "artifact": review_key}
        evidence["runs"].append(run)
    evidence["evidence_body_sha256"] = body_sha256(evidence)
    return evidence


def core_arguments(binding: dict, root: Path) -> dict:
    package = root / binding["asset"]["name"]
    return {"core_behavior": synthetic_core(binding, package, root), "package_path": package, "artifact_root": root}


def synthetic_canary(binding: dict, package: Path) -> dict:
    from codex_base.canary import build_canary_evidence, EXPECTED_PHASES
    return build_canary_evidence(
        release_binding=binding, client_version=package_client(package)["version"],
        foundation_sha256=package_foundation_sha256(package, binding), before_surface_sha256="4" * 64, after_rollback_surface_sha256="4" * 64,
        phase_statuses=EXPECTED_PHASES, discovery=package_discovery(package, binding), preserved_files=8,
        package_path=package,
    )


def add_synthetic_contract(built) -> None:
    """Upgrade a historical archive ONLY as a synthetic lifecycle fixture.

    Production build_release must never inject uncommitted contract bytes.
    This fixture intentionally does not assert real source provenance.
    """
    with zipfile.ZipFile(built.zip_path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["package-manifest.json"])
    entries[PACKAGE_CONTRACT_PATH] = contract_bytes()
    manifest["core_behavior_contract"] = contract_reference()
    manifest["files"] = [row for row in manifest["files"] if row["path"] != PACKAGE_CONTRACT_PATH]
    manifest["files"].append({"path": PACKAGE_CONTRACT_PATH, "sha256": sha256(contract_bytes()), "bytes": len(contract_bytes())})
    manifest["files"].sort(key=lambda row: row["path"])
    manifest["managed_surface"]["replace_files"] = sorted(set(manifest["managed_surface"]["replace_files"] + [PACKAGE_CONTRACT_PATH]))
    entries["package-manifest.json"] = json_bytes(manifest)
    with zipfile.ZipFile(built.zip_path, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    built.manifest["core_behavior_contract"] = contract_reference()
    built.manifest["package_manifest_sha256"] = sha256(entries["package-manifest.json"])
    built.manifest["asset"].update(sha256=sha256(built.zip_path.read_bytes()), bytes=built.zip_path.stat().st_size)
    built.manifest_path.write_bytes(json_bytes(built.manifest))
