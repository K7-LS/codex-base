"""Tamper and scope checks for an explicitly synthetic engine proof fixture."""
import xml.etree.ElementTree as ET
import zipfile
import pytest

from codex_base.core_acceptance import body_sha256, json_bytes, read_json, sha256
from codex_base.foundation_evidence import collect_foundation_artifacts, validate_foundation_engine
from core_evidence_support import minimal_package
from foundation_evidence_support import synthetic_foundation, write_fake_engine


@pytest.fixture
def engine_case(tmp_path):
    binding = {"target": "codex", "version": "0.2.0", "foundation_engine_version": "0.1.0",
               "asset": {"name": "synthetic.zip"}}
    package = minimal_package(tmp_path, binding)
    fixture = synthetic_foundation(binding, package)
    return binding, package, fixture["foundation"], fixture["foundation_artifacts"]


def test_engine_only_proof_binds_actual_package_and_preserves_historical_scope(engine_case, tmp_path):
    binding, package, evidence, artifacts = engine_case
    engine = write_fake_engine(tmp_path / "engine")
    result = validate_foundation_engine(evidence, artifacts, binding, package_path=package, engine_root=engine)
    assert result["FOUNDATION_ENGINE_ACCEPTANCE"] == "PASS"
    assert result["lifecycle_cases"] == 14
    assert evidence["FOUNDATION_SYNTHETIC"] == evidence["INSTALLER_ACCEPTANCE"] == "NOT_RUN"
    (engine / "shared-tools/officecli/officecli.exe").write_bytes(b"changed")
    with pytest.raises(ValueError, match="actual engine files differ"):
        validate_foundation_engine(evidence, artifacts, binding, engine_root=engine)


@pytest.mark.parametrize("mutation", [
    "protocol", "boolean_schema", "historical_pass", "gui_pass", "real_consumer", "model_call",
    "missing_shell", "different_build", "bad_source", "boolean_exit", "missing_scenario",
    "duplicate_scenario", "missing_receipt", "duplicate_receipt", "user_environment", "test_skip", "missing_artifact",
    "overall_environment", "missing_overall_environment", "missing_selected_file",
    "failed_collection", "wrong_collection", "missing_collection",
])
def test_changed_or_incomplete_engine_claim_cannot_pass_even_with_fresh_body_hash(engine_case, mutation):
    binding, package, evidence, artifacts = engine_case
    shell = evidence["engine_lifecycle"]["shells"]["ps7"]
    if mutation == "protocol": evidence["acceptance_protocol"] = "unknown"
    elif mutation == "boolean_schema": evidence["schema_version"] = True
    elif mutation == "historical_pass": evidence["FOUNDATION_SYNTHETIC"] = "PASS"
    elif mutation == "gui_pass": evidence["INSTALLER_ACCEPTANCE"] = "PASS"
    elif mutation == "real_consumer": evidence["scope"]["real_consumer_executed"] = True
    elif mutation == "model_call": evidence["model_requests"] = 1
    elif mutation == "missing_shell": evidence["engine_builds"].pop("ps51")
    elif mutation == "different_build": evidence["engine_builds"]["ps51"]["files"] = {"foundation.ps1": "a"*64}
    elif mutation == "bad_source": evidence["source"]["commit"] = "uncommitted"
    elif mutation == "boolean_exit": evidence["engine_builds"]["ps7"]["returncode"] = False
    elif mutation == "missing_scenario": shell["scenario_ids"].pop()
    elif mutation == "duplicate_scenario": shell["scenario_ids"][-1] = shell["scenario_ids"][0]
    elif mutation == "missing_receipt": shell["receipts"].pop()
    elif mutation == "duplicate_receipt": shell["receipts"][-1] = shell["receipts"][0]
    elif mutation == "user_environment": shell["user_environment_unchanged"] = False
    elif mutation == "test_skip": evidence["pytest"]["counts"]["skipped"] = 1
    elif mutation == "missing_artifact": artifacts.pop(next(iter(artifacts)))
    elif mutation == "overall_environment": evidence["real_user_environment_after"]["PATH"] = "f"*64
    elif mutation == "missing_overall_environment": evidence.pop("real_user_environment_before")
    elif mutation == "missing_selected_file": evidence["pytest"]["selected_files"].pop()
    elif mutation == "failed_collection": evidence["pytest"]["collection"].update(status="FAIL", returncode=1)
    elif mutation == "wrong_collection": evidence["pytest"]["collection"]["stdout"] = "no tests collected"
    elif mutation == "missing_collection": evidence["pytest"].pop("collection")
    evidence["evidence_body_sha256"] = body_sha256(evidence)
    with pytest.raises(ValueError):
        validate_foundation_engine(evidence, artifacts, binding, package_path=package)


@pytest.mark.parametrize("mutation", ["raw_bytes", "wrong_engine", "wrong_scenario", "no_commands", "user_environment", "wrong_env_names", "rollback_drift", "missing_state", "missing_fake_environment"])
def test_rebound_receipt_still_requires_real_scope_invariants(engine_case, mutation):
    binding, package, evidence, artifacts = engine_case
    ref = evidence["engine_lifecycle"]["shells"]["ps7"]["receipts"][0]
    item = artifacts.pop(ref["sha256"])
    if mutation == "raw_bytes":
        item["text"] += "changed"
        artifacts[ref["sha256"]] = item
    else:
        receipt = read_json(item["text"].encode())
        if mutation == "wrong_engine": receipt["engine_sha256"] = "f"*64
        elif mutation == "wrong_scenario": receipt["scenario_id"] = "invented"
        elif mutation == "no_commands": receipt["commands"] = []
        elif mutation == "user_environment": receipt["real_user_environment_after"]["PATH"] = "f"*64
        elif mutation == "wrong_env_names":
            receipt["real_user_environment_before"] = receipt["real_user_environment_after"] = {k: "f"*64 for k in ("x", "y", "z")}
        elif mutation == "rollback_drift": receipt["after"]["files"][".codex/AGENTS.md"] = "a"*64
        elif mutation == "missing_state": receipt.pop("before")
        elif mutation == "missing_fake_environment":
            receipt["before"]["fake_environment"] = receipt["after"]["fake_environment"] = {}
        raw = json_bytes(receipt)
        ref.update(sha256=sha256(raw), bytes=len(raw))
        artifacts[ref["sha256"]] = {"sha256": ref["sha256"], "bytes": len(raw), "text": raw.decode()}
    evidence["evidence_body_sha256"] = body_sha256(evidence)
    with pytest.raises(ValueError):
        validate_foundation_engine(evidence, artifacts, binding, package_path=package)


def test_collects_only_exact_utf8_artifacts_inside_evidence_directory(engine_case, tmp_path):
    _, _, evidence, artifacts = engine_case
    root = tmp_path / "proofs"
    root.mkdir()
    refs = [evidence["pytest"]["junit_artifact"]]
    for shell in evidence["engine_lifecycle"]["shells"].values():
        refs.extend(shell["receipts"])
    for ref in refs:
        path = root / ref["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(artifacts[ref["sha256"]]["text"].encode())
    assert collect_foundation_artifacts(evidence, root) == artifacts
    refs[0]["path"] = "../outside.xml"
    with pytest.raises(ValueError, match="escapes evidence directory"):
        collect_foundation_artifacts(evidence, root)


def test_junit_failure_cannot_be_hidden_by_rehashing_artifact(engine_case):
    binding, package, evidence, artifacts = engine_case
    ref = evidence["pytest"]["junit_artifact"]
    item = artifacts.pop(ref["sha256"])
    raw = item["text"].replace('/>', '><failure/></testcase>', 1).encode()
    ref.update(sha256=sha256(raw), bytes=len(raw))
    evidence["pytest"]["junit_sha256"] = ref["sha256"]
    artifacts[ref["sha256"]] = {"sha256": ref["sha256"], "bytes": len(raw), "text": raw.decode()}
    evidence["evidence_body_sha256"] = body_sha256(evidence)
    with pytest.raises(ValueError, match="JUnit contains failure"):
        validate_foundation_engine(evidence, artifacts, binding, package_path=package)


def _replace_junit(evidence, artifacts, tree):
    ref = evidence["pytest"]["junit_artifact"]
    artifacts.pop(ref["sha256"])
    raw = ET.tostring(tree, encoding="utf-8")
    ref.update(sha256=sha256(raw), bytes=len(raw))
    evidence["pytest"]["junit_sha256"] = ref["sha256"]
    artifacts[ref["sha256"]] = {"sha256": ref["sha256"], "bytes": len(raw), "text": raw.decode()}
    evidence["evidence_body_sha256"] = body_sha256(evidence)


@pytest.mark.parametrize("mutation", ["unrelated", "one_test", "failures", "errors", "skipped", "duplicate"])
def test_junit_actual_identities_and_counters_cannot_contradict_summary(engine_case, mutation):
    binding, package, evidence, artifacts = engine_case
    ref = evidence["pytest"]["junit_artifact"]
    tree = ET.fromstring(artifacts[ref["sha256"]]["text"])
    suite = tree.find("testsuite")
    nodes = list(suite)
    if mutation == "unrelated": nodes[0].set("name", "unrelated")
    elif mutation == "one_test":
        for node in nodes[1:]: suite.remove(node)
    elif mutation == "duplicate": nodes[-1].attrib = nodes[0].attrib.copy()
    else: suite.set(mutation, "1")
    _replace_junit(evidence, artifacts, tree)
    with pytest.raises(ValueError, match="JUnit"):
        validate_foundation_engine(evidence, artifacts, binding, package_path=package)


def test_junit_class_parameter_identity_and_subcheck_aggregate_are_preserved(engine_case):
    binding, package, evidence, artifacts = engine_case
    node = evidence["pytest"]["collected_case_ids"][0]
    file, _ = node.split("::", 1)
    evidence["pytest"]["collected_case_ids"][0] = file + "::TestGroup::test_y[a::b]"
    evidence["pytest"]["collection"]["stdout"] = "\n".join(evidence["pytest"]["collected_case_ids"])
    ref = evidence["pytest"]["junit_artifact"]
    tree = ET.fromstring(artifacts[ref["sha256"]]["text"])
    case = next(tree.iter("testcase"))
    case.set("classname", file[:-3].replace("/", ".") + ".TestGroup")
    case.set("name", "test_y[a::b]")
    tree.find("testsuite").set("tests", "21")
    evidence["pytest"]["counts"]["tests"] = 21
    _replace_junit(evidence, artifacts, tree)
    validate_foundation_engine(evidence, artifacts, binding, package_path=package)


def test_engine_bytes_cannot_be_relabelled_as_another_version(engine_case, tmp_path):
    binding, package, evidence, artifacts = engine_case
    with zipfile.ZipFile(package) as archive:
        entries = {name.replace("/foundation/0.1.0/", "/foundation/9.9.9/"): archive.read(name) for name in archive.namelist()}
    changed = tmp_path / "relabelled.zip"
    with zipfile.ZipFile(changed, "w") as archive:
        for name, data in entries.items(): archive.writestr(name, data)
    binding["foundation_engine_version"] = evidence["engine_version"] = "9.9.9"
    evidence["evidence_body_sha256"] = body_sha256(evidence)
    with pytest.raises(ValueError, match="actual engine VERSION differs"):
        validate_foundation_engine(evidence, artifacts, binding, package_path=changed)
