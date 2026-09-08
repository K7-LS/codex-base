"""Offline integrity/coverage gate, not an execution or reviewer attestation.

The original 15-case specification is immutable for protocol v1. Every claimed
observation must resolve into hashed local evidence. This cannot determine
whether a reviewer is honest; signed execution provenance is a separate trust
boundary. A source-snapshot experiment can never attest to a release package.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any
import zipfile


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "evals/core/contract.json"
SUITE_PATH = ROOT / "evals/core/cases.json"
SUITE_V1_SHA256 = "62b45686075d01277f9c924ca245f105dc5c54ba385f74084b7bdd379218d49c"
PACKAGE_CONTRACT_PATH = ".codex/base/core-eval-contract.json"
CLAIM = "SINGLE_RUN_CONFORMANCE_NOT_RELIABILITY"
ACCEPTANCE_PROTOCOL = "professional-core-v1"
MATCHED_AB_NOT_REQUIRED_REASON = "Historical startup-token benchmark is separate from professional-core conformance."
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_BUNDLE_BYTES = 256 * 1024 * 1024


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"core behavior evidence: {message}")


def _object(value: Any, name: str) -> dict:
    _require(isinstance(value, dict), f"{name} must be an object")
    return value


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def body_sha256(value: dict) -> str:
    return sha256(json_bytes({key: item for key, item in value.items() if key != "evidence_body_sha256"}))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    value = {}
    for key, item in pairs:
        _require(key not in value, "duplicate JSON key")
        value[key] = item
    return value


def read_json(payload: bytes | str) -> Any:
    return json.loads(payload, object_pairs_hook=_unique_object)


def validate_current_wire_keys(value: Any) -> None:
    """Current envelopes must round-trip through case-insensitive PowerShell objects."""
    if isinstance(value, dict):
        folded = set()
        for key, child in value.items():
            _require(isinstance(key, str), "current wire JSON keys must be strings")
            _require(key.casefold() not in folded, "current wire has case-insensitive duplicate JSON keys")
            folded.add(key.casefold())
            validate_current_wire_keys(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            validate_current_wire_keys(child)


def expected_contract(repo_root: Path = ROOT) -> dict:
    suite_path = repo_root / "evals/core/cases.json"
    _require(sha256(suite_path.read_bytes()) == SUITE_V1_SHA256, "original v1 suite bytes changed; a new protocol is required")
    suite = json.loads(suite_path.read_bytes())
    return {
        "schema_version": 1,
        "id": "k7-professional-core-v1",
        "suite_sha256": sha256(suite_path.read_bytes()),
        "minimum_runs_per_case": 1,
        "claim": CLAIM,
        "criteria": {
            case["id"]: {
                group: {
                    f"{case['id']}.{prefix}{index:02}": sha256(text.encode("utf-8"))
                    for index, text in enumerate(case[group], 1)
                }
                for group, prefix in (("must_observe", "M"), ("critical_fail", "F"))
            }
            for case in suite["cases"]
        },
    }


def contract_bytes(repo_root: Path = ROOT) -> bytes:
    payload = (repo_root / "evals/core/contract.json").read_bytes()
    _require(json.loads(payload) == expected_contract(repo_root), "versioned contract differs from original suite")
    return payload


def contract_reference(repo_root: Path = ROOT) -> dict:
    payload = contract_bytes(repo_root)
    value = json.loads(payload)
    return {"id": value["id"], "sha256": sha256(payload), "suite_sha256": value["suite_sha256"]}


def _safe_relative(value: Any) -> str:
    _require(_text(value), "artifact path is missing")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and not any(part in ("", ".", "..") for part in value.split("/"))
             and "\\" not in value and ":" not in value, "unsafe artifact path")
    return value


def _artifact_path(root: Path, relative: str) -> Path:
    relative = _safe_relative(relative)
    root = root.resolve()
    result = root.joinpath(*PurePosixPath(relative).parts)
    _require(result.resolve().is_relative_to(root), "artifact escapes bundle root")
    current = result
    while current != root:
        metadata = current.lstat()
        _require(not current.is_symlink() and not (getattr(metadata, "st_file_attributes", 0) & 0x400),
                 "artifact contains a reparse point")
        current = current.parent
    return result


def package_source_inventory(package_path: Path, binding: dict) -> dict[str, str]:
    """Verify exact package/contract bytes and enumerate its model/runtime surface."""
    _require(binding.get("core_behavior_contract") == contract_reference(), "release contract is missing or stale")
    asset = _object(binding.get("asset"), "asset")
    payload = package_path.read_bytes()
    _require(sha256(payload) == asset.get("sha256") and len(payload) == asset.get("bytes"), "package bytes differ")
    with zipfile.ZipFile(package_path) as archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        _require(len(names) == len(set(names)), "duplicate ZIP entries")
        for name in names:
            _safe_relative(name)
        manifest_payload = archive.read("package-manifest.json")
        manifest = _object(read_json(manifest_payload), "package manifest")
        _require(sha256(manifest_payload) == binding.get("package_manifest_sha256"), "package manifest hash differs")
        _require(manifest.get("target") == binding.get("target") and manifest.get("version") == binding.get("version"),
                 "package identity differs")
        _require(manifest.get("core_behavior_contract") == contract_reference(), "embedded release contract differs")
        _require(archive.read(PACKAGE_CONTRACT_PATH) == contract_bytes(), "embedded contract bytes differ")
        source_names = [name for name in names if name in (".codex/AGENTS.md", ".codex/config.toml", ".codex/hooks.json")
                        or name.startswith((".codex/agents/", ".agents/skills/", ".codex/base/cold/", ".codex/base/runtime/",
                                            "session-tools-baseline/"))]
        _require(".codex/AGENTS.md" in source_names and ".codex/config.toml" in source_names, "package source surface is incomplete")
        return {name: sha256(archive.read(name)) for name in sorted(source_names)}


def package_client(package_path: Path) -> dict:
    with zipfile.ZipFile(package_path) as archive:
        client = _object(read_json(archive.read("package-manifest.json")).get("client"), "package client")
    _require(_text(client.get("id")) and _text(client.get("supported_version")), "package client is incomplete")
    return {"id": client["id"], "version": client["supported_version"]}


def package_discovery(package_path: Path, binding: dict) -> dict:
    names = package_source_inventory(package_path, binding)
    return {
        "agents": sum(name.startswith(".codex/agents/") and len(PurePosixPath(name).parts) == 3 and name.endswith(".toml") for name in names),
        # The no-model lifecycle canary seeds exactly one preserved local skill.
        "skills": 1 + len({PurePosixPath(name).parts[2] for name in names
                           if name.startswith((".agents/skills/", "session-tools-baseline/tools/"))
                           and len(PurePosixPath(name).parts) == 4 and name.endswith("/SKILL.md")}),
    }


def package_foundation_sha256(package_path: Path, binding: dict) -> str:
    version = binding.get("foundation_engine_version")
    _require(_text(version) and "/" not in version and "\\" not in version and ":" not in version, "foundation version is invalid")
    with zipfile.ZipFile(package_path) as archive:
        return sha256(archive.read(f".codex/base/foundation/{version}/foundation.ps1"))


def _load_artifacts(evidence: dict, root: Path) -> dict[str, bytes]:
    records = _object(evidence.get("artifacts"), "artifacts")
    _require(bool(records), "artifacts are missing")
    payloads = {}
    paths = set()
    total = 0
    for key, record in records.items():
        _require(_text(key), "artifact id is empty")
        record = _object(record, "artifact")
        relative = _safe_relative(record.get("path"))
        _require(relative.startswith("core-artifacts/"), "artifact must stay in reserved core-artifacts directory")
        _require(relative.casefold() not in paths, "duplicate artifact path")
        paths.add(relative.casefold())
        size = record.get("bytes")
        _require(_positive(size) and size <= MAX_ARTIFACT_BYTES and _digest(record.get("sha256")), "invalid artifact identity")
        total += size
        _require(total <= MAX_BUNDLE_BYTES, "artifact bundle is too large")
        try:
            path = _artifact_path(root, relative)
            _require(path.stat().st_size == size, "artifact size differs")
            payload = path.read_bytes()
        except OSError as error:
            raise ValueError("core behavior evidence: artifact is unavailable") from error
        _require(sha256(payload) == record["sha256"], "artifact hash differs")
        payloads[key] = payload
    return payloads


def _event(pointer: Any, payloads: dict[str, bytes], expected_artifact: str) -> dict:
    pointer = _object(pointer, "event pointer")
    _require(pointer.get("artifact") == expected_artifact and expected_artifact in payloads, "event points to another artifact")
    lines = payloads[expected_artifact].splitlines()
    line = pointer.get("line")
    _require(_positive(line) and line <= len(lines), "event line does not exist")
    payload = lines[line - 1]
    _require(sha256(payload) == pointer.get("sha256"), "event pointer hash differs")
    try:
        return _object(read_json(payload), "event")
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("core behavior evidence: event is not JSON") from error


def _behavioral_event(event: dict, run_id: str) -> bool:
    _require(event.get("run_id") == run_id, "behavioral event belongs to another run")
    kind = event.get("kind")
    if kind in ("assistant_message", "user_message"):
        _require(_text(event.get("text")), "message observation is empty")
        return kind == "assistant_message"
    elif kind in ("tool_call", "tool_result", "client_event"):
        payload = _object(event.get("payload"), "behavioral event payload")
        _require(bool(payload), "behavioral event payload is empty")
        if kind == "client_event":
            params = _object(payload.get("params"), "native event params")
            item = _object(params.get("item"), "native event item")
            _require(payload.get("method") == "item/completed" and item.get("type") == "agentMessage" and _text(item.get("text")),
                     "native event is not a completed model message")
        else:
            _require(_text(payload.get("name")) and ("arguments" if kind == "tool_call" else "result") in payload,
                     "tool event is incomplete")
        return True
    else:
        raise ValueError("core behavior evidence: unsupported or missing behavioral event kind")


def validate_core_behavior(
    evidence: Any, binding: dict, *, package_path: Path, artifact_root: Path,
) -> dict:
    """Require all original criteria, independent review and actual bound artifacts.

    No network, model calls, installs, mutable profile reads or release actions.
    Model/effort names are observations and deliberately have no allowlist.
    """
    evidence = _object(evidence, "core_behavior")
    _require(evidence.get("schema_version") == 1 and evidence.get("kind") == "core_behavior_evidence", "protocol identity differs")
    _require(evidence.get("evaluation_mode") == "RELEASE_PACKAGE", "source snapshot is not release evidence")
    _require(evidence.get("protocol") == contract_reference(), "protocol contract differs")
    _require(evidence.get("release_binding") == binding, "release binding differs")
    _require(evidence.get("CORE_BEHAVIOR") == "PASS" and evidence.get("claim") == CLAIM, "conformance is not PASS")
    _require(evidence.get("evidence_body_sha256") == body_sha256(evidence), "body hash differs")
    inventory = package_source_inventory(package_path, binding)
    expected_client = package_client(package_path)
    inventory_hash = sha256(json_bytes(inventory))
    payloads = _load_artifacts(evidence, artifact_root)
    for field in ("suite_artifact", "harness_artifact", "evaluator_artifact"):
        _require(evidence.get(field) in payloads, f"{field} is missing")
    _require(sha256(payloads[evidence["suite_artifact"]]) == contract_reference()["suite_sha256"], "suite artifact differs")
    runs = evidence.get("runs")
    _require(isinstance(runs, list) and bool(runs), "runs are missing")
    contract = expected_contract()
    case_specs = {case["id"]: case for case in json.loads(SUITE_PATH.read_bytes())["cases"]}
    seen_runs = set()
    seen_cases = set()
    for run in runs:
        run = _object(run, "run")
        run_id, case_id = run.get("id"), run.get("case_id")
        _require(_text(run_id) and run_id not in seen_runs, "missing or duplicate run id")
        seen_runs.add(run_id)
        _require(case_id in contract["criteria"], "unknown case id")
        seen_cases.add(case_id)
        _require(run.get("status") == "PASS" and _text(run.get("subject_id")), "run is incomplete")
        events = run.get("events_artifact")
        _require(events in payloads, "run events are missing")
        runtime = _object(run.get("runtime"), "runtime observations")
        client = _object(runtime.get("client"), "client observation")
        _require(_text(client.get("id")) and _text(client.get("version")) and _text(runtime.get("model"))
                 and _text(runtime.get("reasoning_effort")), "effective runtime observation is missing")
        _require(client == expected_client, "observed client differs from package contract")
        _require(runtime.get("effective_config_artifact") in payloads, "effective config artifact is missing")
        _require(run.get("materialized_source_inventory") == inventory, "materialized source bytes differ from package")
        loaded_inventory = _object(run.get("loaded_source_inventory"), "loaded source inventory")
        _require(".codex/AGENTS.md" in loaded_inventory and all(name in inventory and _digest(digest) and inventory[name] == digest
                                                             for name, digest in loaded_inventory.items()),
                 "loaded source bytes differ from package")
        loaded_hash = sha256(json_bytes(loaded_inventory))
        loaded = _event(run.get("source_load_event"), payloads, events)
        _require(loaded.get("kind") == "loaded_source" and loaded.get("run_id") == run_id
                 and loaded.get("source_inventory_sha256") == inventory_hash and loaded.get("runtime") == runtime
                 and loaded.get("loaded_source_inventory_sha256") == loaded_hash
                 and loaded.get("harness_sha256") == sha256(payloads[evidence["harness_artifact"]]),
                 "source loading observation differs")
        fixtures = run.get("fixture_artifacts")
        _require(isinstance(fixtures, list) and bool(fixtures) and len(fixtures) == len(set(fixtures))
                 and all(item in payloads for item in fixtures), "fixture artifacts are missing or duplicated")
        fixture_hashes = {item: sha256(payloads[item]) for item in fixtures}
        _require(loaded.get("fixture_hashes") == fixture_hashes, "observed fixture hashes differ")
        submitted = _event(run.get("input_event"), payloads, events)
        _require(submitted.get("kind") == "user_message" and submitted.get("run_id") == run_id
                 and submitted.get("case_id") == case_id and submitted.get("text") == case_specs[case_id]["prompt"]
                 and submitted.get("case_spec_sha256") == sha256(json_bytes(case_specs[case_id]))
                 and submitted.get("fixture_hashes") == fixture_hashes,
                 "submitted input does not match original case")
        if "mid_task_user_message" in case_specs[case_id]:
            mid = _event(run.get("mid_task_input_event"), payloads, events)
            _require(mid.get("kind") == "user_message" and mid.get("run_id") == run_id
                     and mid.get("text") == case_specs[case_id]["mid_task_user_message"], "mid-task input is missing or differs")
            before_mid = _object(run.get("pre_mid_task_observation"), "pre-steer observation")
            after_mid = _object(run.get("post_mid_task_observation"), "post-steer observation")
            _require(_behavioral_event(_event(before_mid, payloads, events), run_id)
                     and _behavioral_event(_event(after_mid, payloads, events), run_id)
                     and run["input_event"]["line"] < before_mid["line"] < run["mid_task_input_event"]["line"] < after_mid["line"],
                     "mid-task change was not observed during model work")
        statuses = {}
        for group, passed in (("must_observe", "PASS"), ("critical_fail", "ABSENT")):
            criteria = _object(run.get(group), group)
            _require(set(criteria) == set(contract["criteria"][case_id][group]), "missing or unexpected criterion id")
            for criterion_id, observation in criteria.items():
                observation = _object(observation, "criterion")
                _require(observation.get("status") == passed and _text(observation.get("reason")), f"{criterion_id} is unobserved or failed")
                pointers = observation.get("evidence")
                _require(isinstance(pointers, list) and bool(pointers), "criterion evidence is missing")
                subject_observed = False
                for pointer in pointers:
                    observation_event = _event(pointer, payloads, events)
                    is_subject = _behavioral_event(observation_event, run_id)
                    if is_subject:
                        _require(pointer["line"] > run["input_event"]["line"], "model observation precedes case input")
                    subject_observed = is_subject or subject_observed
                _require(subject_observed, "criterion lacks a model or tool observation")
                statuses[criterion_id] = passed
        review = _object(run.get("review"), "review")
        _require(review.get("independent") is True and _text(review.get("reviewer_id"))
                 and review["reviewer_id"] != run["subject_id"], "independent reviewer is missing")
        _require(review.get("artifact") in payloads, "review artifact is missing")
        reviewed = _object(read_json(payloads[review["artifact"]]), "review artifact")
        _require(reviewed.get("run_id") == run_id and reviewed.get("reviewer_id") == review["reviewer_id"]
                 and reviewed.get("independent") is True and reviewed.get("verdict") == "PASS"
                 and reviewed.get("criterion_statuses") == statuses
                 and reviewed.get("events_sha256") == sha256(payloads[events])
                 and reviewed.get("source_inventory_sha256") == inventory_hash
                 and reviewed.get("case_id") == case_id
                 and reviewed.get("input_event_sha256") == run["input_event"]["sha256"]
                 and reviewed.get("loaded_source_inventory_sha256") == loaded_hash
                 and reviewed.get("evaluator_sha256") == sha256(payloads[evidence["evaluator_artifact"]]),
                 "review is incomplete or bound to other bytes")
    _require(seen_cases == set(contract["criteria"]), "not all 15 cases are covered")
    return {"CORE_BEHAVIOR": "PASS", "cases": len(seen_cases), "runs": len(runs), "claim": CLAIM}


def copy_core_artifacts(evidence: dict, source_root: Path, destination_root: Path) -> None:
    """Copy only already-validated relative artifacts with unchanged bytes."""
    for record in evidence["artifacts"].values():
        source = _artifact_path(source_root, record["path"])
        root = destination_root.resolve()
        _require(record["path"].startswith("core-artifacts/"), "artifact must stay in reserved core-artifacts directory")
        destination = root.joinpath(*PurePosixPath(record["path"]).parts)
        _require(destination.resolve().is_relative_to(root), "destination artifact escapes bundle root")
        current = destination.parent
        while current != root:
            try:
                metadata = current.lstat()
                _require(not current.is_symlink() and not (getattr(metadata, "st_file_attributes", 0) & 0x400),
                         "destination artifact contains a reparse point")
            except FileNotFoundError:
                pass
            current = current.parent
        _require(not destination.exists(), "destination artifact already exists")
        payload = source.read_bytes()
        _require(sha256(payload) == record["sha256"] and len(payload) == record["bytes"], "artifact changed before copy")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(payload)
