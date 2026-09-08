"""Fail-closed conformance-gate tests; no model calls or actual release claims."""

import copy
import json

import pytest
from foundation_evidence_support import synthetic_foundation

from codex_base.core_acceptance import (
    ACCEPTANCE_PROTOCOL, MATCHED_AB_NOT_REQUIRED_REASON,
    body_sha256, contract_bytes, expected_contract, read_json, sha256, validate_core_behavior,
)
from codex_base.promotion import _verify_evidence, REQUIRED_FULL_RELEASE_GATES
from core_evidence_support import minimal_package, synthetic_core


@pytest.fixture
def bundle(tmp_path):
    binding = {"target": "codex", "version": "test", "asset": {"name": "test.zip"}}
    package = minimal_package(tmp_path, binding)
    evidence = synthetic_core(binding, package, tmp_path)
    return evidence, binding, package, tmp_path


def validate(bundle):
    evidence, binding, package, root = bundle
    return validate_core_behavior(evidence, binding, package_path=package, artifact_root=root)


def test_contract_keeps_all_original_criteria_and_single_run_claim():
    contract = json.loads(contract_bytes())
    assert contract == expected_contract()
    assert len(contract["criteria"]) == 15
    assert contract["minimum_runs_per_case"] == 1
    assert contract["claim"] == "SINGLE_RUN_CONFORMANCE_NOT_RELIABILITY"


def test_complete_synthetic_bundle_validates_integrity_only(bundle):
    result = validate(bundle)
    assert result["cases"] == 15 and result["runs"] == 15


@pytest.mark.parametrize("model,effort", [("observed-model-a", "observed-effort-a"), ("observed-model-b", "observed-effort-b")])
def test_observed_model_and_effort_are_not_pinned(bundle, model, effort):
    _, binding, package, root = bundle
    evidence = synthetic_core(binding, package, root, model=model, effort=effort)
    assert validate((evidence, binding, package, root))["CORE_BEHAVIOR"] == "PASS"


@pytest.mark.parametrize("tamper", [
    "missing_case", "duplicate_run", "unknown_case", "missing_criterion", "extra_criterion",
    "FAIL", "NOT_OBSERVED", "NOT_EXERCISED", "critical_fail", "empty_reason", "empty_pointers",
    "fake_line", "fake_event_hash", "other_event", "metadata_observation", "stale_source", "stale_load_event", "stale_runtime",
    "same_reviewer", "missing_review", "snapshot", "wrong_suite", "wrong_contract", "other_package",
    "missing_artifact", "stale_artifact", "path_escape", "stale_harness", "stale_evaluator", "stale_fixture", "different_client", "external_null_source",
])
def test_recomputed_top_pass_cannot_hide_bad_evidence(bundle, tamper):
    evidence, binding, package, root = bundle
    run = evidence["runs"][0]
    criterion = run["must_observe"]["C01.M01"]
    pointer = criterion["evidence"][0]
    if tamper == "missing_case": evidence["runs"].pop()
    elif tamper == "duplicate_run": evidence["runs"].append(copy.deepcopy(run))
    elif tamper == "unknown_case": run["case_id"] = "C16"
    elif tamper == "missing_criterion": del run["must_observe"]["C01.M01"]
    elif tamper == "extra_criterion": run["must_observe"]["C01.M00"] = copy.deepcopy(criterion)
    elif tamper in ("FAIL", "NOT_OBSERVED", "NOT_EXERCISED"): criterion["status"] = tamper
    elif tamper == "critical_fail": run["critical_fail"]["C01.F01"]["status"] = "PRESENT"
    elif tamper == "empty_reason": criterion["reason"] = ""
    elif tamper == "empty_pointers": criterion["evidence"] = []
    elif tamper == "fake_line": pointer["line"] = 999999
    elif tamper == "fake_event_hash": pointer["sha256"] = "0" * 64
    elif tamper == "other_event": pointer["artifact"] = "C02-events"
    elif tamper == "metadata_observation": criterion["evidence"] = [dict(run["source_load_event"])]
    elif tamper == "stale_source": run["loaded_source_inventory"] = {".codex/AGENTS.md": "0" * 64}
    elif tamper == "stale_load_event": run["source_load_event"]["line"] = 2
    elif tamper == "stale_runtime": run["runtime"] = {**run["runtime"], "model": "unobserved-model"}
    elif tamper == "same_reviewer": run["review"]["reviewer_id"] = run["subject_id"]
    elif tamper == "missing_review": run["review"]["artifact"] = "absent"
    elif tamper == "snapshot": evidence["evaluation_mode"] = "SOURCE_SNAPSHOT"
    elif tamper == "wrong_suite": evidence["suite_artifact"] = "fixture"
    elif tamper == "wrong_contract": evidence["protocol"] = {**evidence["protocol"], "sha256": "0" * 64}
    elif tamper == "other_package": package.write_bytes(package.read_bytes() + b"drift")
    elif tamper == "missing_artifact": (root / evidence["artifacts"]["C01-events"]["path"]).unlink()
    elif tamper == "stale_artifact": (root / evidence["artifacts"]["C01-events"]["path"]).write_bytes(b"drift")
    elif tamper == "path_escape": evidence["artifacts"]["C01-events"]["path"] = "../elsewhere"
    elif tamper == "different_client": run["runtime"]["client"] = {"id": "codex-cli", "version": "unproven-new-client"}
    elif tamper == "external_null_source": run["loaded_source_inventory"]["C:/foreign/SKILL.md"] = None
    elif tamper.startswith("stale_"):
        key = tamper.removeprefix("stale_")
        payload = b"changed but self-hashed artifact\n"
        record = evidence["artifacts"][key]
        (root / record["path"]).write_bytes(payload)
        record.update(sha256=sha256(payload), bytes=len(payload))
    evidence["evidence_body_sha256"] = body_sha256(evidence)
    with pytest.raises(ValueError, match="core behavior"):
        validate(bundle)


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("tamper", ["missing_core", "failed_criterion", "stripped_contract", "case_colliding_wire_key"])
def test_last_promotion_gate_does_not_trust_top_pass(bundle, legacy, tamper):
    core, binding, package, root = bundle
    final = {"schema_version": 1, "target": "codex", "version": "test", "release_binding": binding,
             **{gate: "PASS" for gate in REQUIRED_FULL_RELEASE_GATES}, "PROGRAM_RELEASE": "1/3", "core_behavior_evidence": core}
    final["FOUNDATION_SYNTHETIC"] = "NOT_RUN"
    final.update(synthetic_foundation(binding, package))
    final.update(acceptance_protocol=ACCEPTANCE_PROTOCOL, MATCHED_AB="NOT_REQUIRED", matched_ab_not_required_reason=MATCHED_AB_NOT_REQUIRED_REASON)
    if legacy:
        final["release_integrity_contract"] = {"mode": "CONSUMER_VERIFIED_BEFORE_EVIDENCE"}
    if tamper == "missing_core": del final["core_behavior_evidence"]
    elif tamper == "case_colliding_wire_key": final["core_behavior"] = core
    elif tamper == "failed_criterion":
        core["runs"][0]["must_observe"]["C01.M01"]["status"] = "NOT_EXERCISED"
        core["evidence_body_sha256"] = body_sha256(core)
    else:
        del binding["core_behavior_contract"]
        core["evidence_body_sha256"] = body_sha256(core)
    final["evidence_body_sha256"] = body_sha256(final)
    with pytest.raises(ValueError, match="core behavior|wire key collides"):
        _verify_evidence(final, binding, require_full_release=True, package_path=package, artifact_root=root)


def test_duplicate_criterion_json_keys_are_rejected_before_composition():
    with pytest.raises(ValueError, match="duplicate JSON key"):
        read_json('{"C01.M01":{"status":"FAIL"},"C01.M01":{"status":"PASS"}}')


@pytest.mark.parametrize("alias", ["Core_Behavior", "CORE_BEHAVIOR_EVIDENCE", "EVIDENCE_BODY_SHA256", "nested"])
def test_promotion_rejects_case_collisions_even_after_rehash(bundle, alias):
    core, binding, package, root = bundle
    final = {"schema_version": 1, "target": "codex", "version": "test", "release_binding": binding,
             **{gate: "PASS" for gate in REQUIRED_FULL_RELEASE_GATES}, "PROGRAM_RELEASE": "1/3", "core_behavior_evidence": core}
    final[alias] = {"scope": 1, "Scope": 2} if alias == "nested" else {}
    final["evidence_body_sha256"] = body_sha256(final)
    with pytest.raises(ValueError, match="case-insensitive duplicate"):
        _verify_evidence(final, binding, require_full_release=True, package_path=package, artifact_root=root)


def test_embedded_contract_cannot_be_stripped_and_rehashed(bundle):
    import zipfile
    evidence, binding, package, root = bundle
    with zipfile.ZipFile(package) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["package-manifest.json"])
    del manifest["core_behavior_contract"]
    entries["package-manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(package, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    binding["asset"].update(sha256=sha256(package.read_bytes()), bytes=package.stat().st_size)
    binding["package_manifest_sha256"] = sha256(entries["package-manifest.json"])
    evidence["evidence_body_sha256"] = body_sha256(evidence)
    with pytest.raises(ValueError, match="embedded release contract"):
        validate(bundle)


def _rewrite_event_and_rehash_every_link(bundle, index, changed):
    evidence, _, _, root = bundle
    run = evidence["runs"][0]
    record = evidence["artifacts"][run["events_artifact"]]
    path = root / record["path"]
    lines = path.read_bytes().splitlines()
    lines[index - 1] = json.dumps(changed, sort_keys=True).encode()
    payload = b"\n".join(lines) + b"\n"
    path.write_bytes(payload)
    record.update(sha256=sha256(payload), bytes=len(payload))
    for field in ("source_load_event", "input_event"):
        if run[field]["line"] == index: run[field]["sha256"] = sha256(lines[index - 1])
    for group in ("must_observe", "critical_fail"):
        for criterion in run[group].values():
            for pointer in criterion["evidence"]:
                if pointer["line"] == index: pointer["sha256"] = sha256(lines[index - 1])
    review_record = evidence["artifacts"][run["review"]["artifact"]]
    review_path = root / review_record["path"]
    reviewed = json.loads(review_path.read_bytes())
    reviewed["events_sha256"] = record["sha256"]
    reviewed["input_event_sha256"] = run["input_event"]["sha256"]
    review_payload = json.dumps(reviewed, sort_keys=True).encode()
    review_path.write_bytes(review_payload)
    review_record.update(sha256=sha256(review_payload), bytes=len(review_payload))
    evidence["evidence_body_sha256"] = body_sha256(evidence)


@pytest.mark.parametrize("changed", [{}, {"kind": None}, {"kind": ""}, {"kind": "assistant_message", "text": ""},
                                      {"kind": "client_event", "payload": {}}, {"kind": "tool_result", "payload": {"unrelated": True}}])
def test_structurally_empty_events_fail_after_all_hashes_recomputed(bundle, changed):
    _rewrite_event_and_rehash_every_link(bundle, 3, {**changed, "run_id": bundle[0]["runs"][0]["id"]})
    with pytest.raises(ValueError, match="core behavior"):
        validate(bundle)


def test_actual_input_cannot_be_relabelled_as_another_case(bundle):
    evidence, _, _, root = bundle
    run = evidence["runs"][0]
    lines = (root / evidence["artifacts"][run["events_artifact"]]["path"]).read_bytes().splitlines()
    submitted = json.loads(lines[1])
    submitted["text"] = "An unrelated actual question"
    _rewrite_event_and_rehash_every_link(bundle, 2, submitted)
    with pytest.raises(ValueError, match="submitted input"):
        validate(bundle)


def test_artifact_cannot_collide_with_release_manifest(bundle):
    evidence = bundle[0]
    evidence["artifacts"]["fixture"]["path"] = "release-manifest.json"
    evidence["evidence_body_sha256"] = body_sha256(evidence)
    with pytest.raises(ValueError, match="reserved core-artifacts"):
        validate(bundle)


def test_only_user_input_is_not_an_observation_of_the_model(bundle):
    evidence = bundle[0]
    run = evidence["runs"][0]
    for criterion in run["must_observe"].values():
        criterion["evidence"] = [dict(run["input_event"])]
    evidence["evidence_body_sha256"] = body_sha256(evidence)
    with pytest.raises(ValueError, match="lacks a model or tool"):
        validate(bundle)


def test_native_thread_metadata_is_not_model_behavior(bundle):
    _rewrite_event_and_rehash_every_link(bundle, 3, {"kind": "client_event", "run_id": bundle[0]["runs"][0]["id"],
                                                   "payload": {"method": "thread/started", "params": {"thread": {"id": "t"}}}})
    with pytest.raises(ValueError, match="core behavior"):
        validate(bundle)


def test_mid_task_case_requires_actual_steering_between_observations(bundle):
    evidence = bundle[0]
    run = next(run for run in evidence["runs"] if run["case_id"] == "C07")
    del run["mid_task_input_event"]
    evidence["evidence_body_sha256"] = body_sha256(evidence)
    with pytest.raises(ValueError, match="event pointer"):
        validate(bundle)
