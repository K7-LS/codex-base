"""Fail-closed conformance-gate tests; no model calls or actual release claims."""

import copy
import json

import pytest
from foundation_evidence_support import synthetic_foundation

from codex_base.core_acceptance import (
    ACCEPTANCE_PROTOCOL, MATCHED_AB_NOT_REQUIRED_REASON,
    body_sha256, client_matches_package, contract_bytes, expected_contract, read_json, sha256, validate_core_behavior,
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


@pytest.mark.parametrize("version", ["0.153.1", "0.155.0-alpha.16.4", "1.20.0"])
def test_release_client_contract_does_not_pin_cli_version(version):
    package_client = {"id": "codex-cli", "version": "0.0.0"}
    assert client_matches_package({"id": "codex-cli", "version": version}, package_client)
    assert not client_matches_package({"id": "other-cli", "version": version}, package_client)
    assert not client_matches_package({"id": "codex-cli", "version": ""}, package_client)


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


def test_027_core_evidence_requires_workspace_runs(tmp_path):
    binding = {"target": "codex", "version": "0.2.7", "asset": {"name": "candidate.zip"}}
    package = minimal_package(tmp_path, binding)
    evidence = synthetic_core(binding, package, tmp_path)
    with pytest.raises(ValueError, match="workspace behavior evidence"):
        validate_core_behavior(evidence, binding, package_path=package, artifact_root=tmp_path)


def test_027_promotion_rejects_installation_only():
    from codex_base.acceptance import evidence_body_sha256
    from codex_base.final_evidence import INSTALL_ACCEPTANCE_PROTOCOL

    binding = {"version": "0.2.7"}
    evidence = {
        "schema_version": 1, "target": "codex", "version": "0.2.7",
        "release_binding": binding, "acceptance_protocol": INSTALL_ACCEPTANCE_PROTOCOL,
        "FOUNDATION_SYNTHETIC": "NOT_RUN", "MATCHED_AB": "NOT_REQUIRED",
        "matched_ab_not_required_reason": MATCHED_AB_NOT_REQUIRED_REASON,
    }
    evidence["evidence_body_sha256"] = evidence_body_sha256(evidence)
    with pytest.raises(ValueError, match="requires workspace behavior"):
        _verify_evidence(evidence, binding, require_full_release=True)



def _workspace_bundle(tmp_path):
    from codex_base.core_acceptance import WORKSPACE_BASELINE_SHA256, WORKSPACE_CASE_IDS, WORKSPACE_SUITE_PATH

    binding = {"target": "codex", "version": "0.2.7", "asset": {"name": "candidate.zip"}}
    package = minimal_package(tmp_path, binding)
    evidence = synthetic_core(binding, package, tmp_path)

    def artifact(key, payload):
        relative = f"core-artifacts/{key}.json"
        (tmp_path / relative).write_bytes(payload)
        evidence["artifacts"][key] = {"path": relative, "sha256": sha256(payload), "bytes": len(payload)}
        return key

    suite = WORKSPACE_SUITE_PATH.read_bytes()
    workspace = {"suite_artifact": artifact("workspace-suite", suite), "cases": {}}
    for spec in json.loads(suite)["cases"]:
        case_id = spec["id"]
        if case_id not in WORKSPACE_CASE_IDS:
            continue
        fixture = f"Synthetic fixture {case_id}".encode()
        case = {"fixture_artifact": artifact(f"{case_id}-fixture", fixture)}
        hashes = {}
        checked = {}
        if case_id in ("W08", "W09"):
            from io import BytesIO
            from zipfile import ZipFile

            for outcome in ("negative", "final"):
                stream = BytesIO()
                with ZipFile(stream, "w") as archive:
                    part = "word/document.xml" if case_id == "W08" else "xl/workbook.xml"
                    archive.writestr(part, f"<test>{case_id} {outcome}</test>")
                payload = stream.getvalue()
                case[f"{outcome}_artifact"] = artifact(f"{case_id}-{outcome}", payload)
                checked[outcome] = sha256(payload)
        for side, package_hash in (("baseline", WORKSPACE_BASELINE_SHA256),
                                   ("candidate", binding["asset"]["sha256"])):
            run_id = f"{case_id}-{side}"
            key = f"{run_id}-events"
            events = [
                {"kind": "workspace_loaded", "run_id": run_id, "case_id": case_id,
                 "subject_id": "test-model-subject", "package_sha256": package_hash,
                 "fixture_sha256": sha256(fixture),
                 "runtime": {"client_version": "1.0.0", "host": "test-host",
                             "model": "test-model", "reasoning_effort": "test-effort"}},
                {"kind": "user_message", "run_id": run_id, "text": spec["input"]},
                {"kind": "assistant_message", "run_id": run_id, "text": "Synthetic unit-test observation"},
            ]
            fields = ["loaded", "input", "result"]
            if side == "candidate" and checked:
                for outcome, verdict in (("negative", "BLOCKED"), ("final", "PASS")):
                    events.append({
                        "kind": "tool_result", "run_id": run_id,
                        "payload": {"name": "check_delivery" if case_id == "W08" else "formuladiff",
                                    "result": {"artifact_sha256": checked[outcome], "verdict": verdict}},
                    })
                    fields.append(f"{outcome}_check")
            if case_id == "W12":
                events.append({"kind": "user_message", "run_id": run_id, "text": "New document arrives"})
                fields.append("changed")
                if side == "candidate":
                    events.extend([
                        {"kind": "tool_call", "run_id": run_id,
                         "payload": {"name": "request_user_input_async", "arguments": {"question": "Which revision?"}}},
                        {"kind": "user_message", "run_id": run_id, "text": "Use revision 2"},
                    ])
                    fields.extend(["question", "reply"])
                events.append({"kind": "assistant_message", "run_id": run_id, "text": "Work after new input"})
                fields.append("continued")
            lines = [json.dumps(event).encode() for event in events]
            payload = b"\n".join(lines) + b"\n"
            hashes[side] = sha256(payload)
            case[side] = {"events_artifact": artifact(key, payload)}
            for number, field in enumerate(fields, 1):
                case[side][field] = {"artifact": key, "line": number, "sha256": sha256(lines[number - 1])}
        review = {"case_id": case_id, "independent": True, "reviewer_id": "test-independent-reviewer",
                  "baseline_verdict": "FAIL", "events_sha256": hashes,
                  "candidate_checks": {criterion: "PASS" for criterion in spec["reviewer_checks"]}}
        case["review_artifact"] = artifact(f"{case_id}-review", json.dumps(review).encode())
        workspace["cases"][case_id] = case
    evidence["workspace_behavior"] = workspace
    evidence["evidence_body_sha256"] = body_sha256(evidence)
    return evidence, binding, package, tmp_path


def test_027_accepts_all_workspace_cases_with_independent_reviews(tmp_path):
    result = validate(_workspace_bundle(tmp_path))
    assert result["CORE_BEHAVIOR"] == "PASS"


@pytest.mark.parametrize("tamper", ["missing_case", "failed_criterion", "self_review", "reused_events"])
def test_027_workspace_gate_fails_closed(tmp_path, tamper):
    evidence, binding, package, root = _workspace_bundle(tmp_path)
    cases = evidence["workspace_behavior"]["cases"]
    if tamper == "missing_case":
        del cases["W07"]
    elif tamper == "reused_events":
        cases["W07"]["candidate"] = cases["W07"]["baseline"]
    else:
        record = evidence["artifacts"][cases["W07"]["review_artifact"]]
        path = root / record["path"]
        review = json.loads(path.read_bytes())
        if tamper == "failed_criterion":
            review["candidate_checks"][next(iter(review["candidate_checks"]))] = "FAIL"
        else:
            review["reviewer_id"] = "test-model-subject"
        payload = json.dumps(review).encode()
        path.write_bytes(payload)
        record.update(sha256=sha256(payload), bytes=len(payload))
    evidence["evidence_body_sha256"] = body_sha256(evidence)
    with pytest.raises(ValueError, match=r"workspace cases|W07"):
        validate((evidence, binding, package, root))


@pytest.mark.parametrize("case_id, field", [
    ("W08", "negative_check"), ("W09", "final_check"), ("W12", "changed"), ("W12", "reply"),
])
def test_027_requires_case_specific_observations(tmp_path, case_id, field):
    evidence, binding, package, root = _workspace_bundle(tmp_path)
    del evidence["workspace_behavior"]["cases"][case_id]["candidate"][field]
    evidence["evidence_body_sha256"] = body_sha256(evidence)
    with pytest.raises(ValueError, match="workspace observation"):
        validate((evidence, binding, package, root))


def test_027_rejects_same_file_as_both_rejected_and_accepted(tmp_path):
    evidence, binding, package, root = _workspace_bundle(tmp_path)
    case = evidence["workspace_behavior"]["cases"]["W09"]
    negative = evidence["artifacts"][case["negative_artifact"]]
    final = evidence["artifacts"][case["final_artifact"]]
    (root / final["path"]).write_bytes((root / negative["path"]).read_bytes())
    final.update(sha256=negative["sha256"], bytes=negative["bytes"])

    candidate = case["candidate"]
    events = evidence["artifacts"][candidate["events_artifact"]]
    event_path = root / events["path"]
    lines = event_path.read_bytes().splitlines()
    pointer = candidate["final_check"]
    position = pointer["line"] - 1
    event = json.loads(lines[position])
    event["payload"]["result"]["artifact_sha256"] = negative["sha256"]
    lines[position] = json.dumps(event).encode()
    pointer["sha256"] = sha256(lines[position])
    payload = b"\n".join(lines) + b"\n"
    event_path.write_bytes(payload)
    events.update(sha256=sha256(payload), bytes=len(payload))

    record = evidence["artifacts"][case["review_artifact"]]
    review_path = root / record["path"]
    review = json.loads(review_path.read_bytes())
    review["events_sha256"]["candidate"] = events["sha256"]
    payload = json.dumps(review).encode()
    review_path.write_bytes(payload)
    record.update(sha256=sha256(payload), bytes=len(payload))
    evidence["evidence_body_sha256"] = body_sha256(evidence)

    with pytest.raises(ValueError, match="negative and final artifacts are identical"):
        validate((evidence, binding, package, root))
