from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from codex_base.acceptance import (
    evidence_body_sha256,
    release_binding_from_manifest,
)
from codex_base.promotion import (
    REQUIRED_FULL_RELEASE_GATES,
    create_package_acceptance,
    promote_candidate,
)
from codex_base.release import bind_acceptance_evidence, build_release


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _foundation(root: Path) -> Path:
    root.mkdir()
    script = root / "foundation.ps1"
    script.write_text("exit 0\n", encoding="utf-8")
    (root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "protocol_version": 1,
        "engine_version": "0.1.0",
        "network": "offline",
        "commands": [
            "doctor",
            "install",
            "inventory",
            "plan",
            "rollback",
        ],
        "supported_powershell": ["5.1", "7"],
        "foundation_ps1_sha256": hashlib.sha256(
            script.read_bytes()
        ).hexdigest(),
    }
    (root / "engine-manifest.json").write_bytes(_json_bytes(manifest))
    return root


def _candidate(repo_root: Path, tmp_path: Path) -> tuple[Path, dict[str, object]]:
    built = build_release(
        repo_root,
        tmp_path / "build",
        "0.1.0",
        _foundation(tmp_path / "foundation"),
    )
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    for path in (
        built.zip_path,
        built.manifest_path,
        built.component_lock_path,
    ):
        shutil.copy2(path, candidate / path.name)
    binding = release_binding_from_manifest(built.manifest)
    offline = {
        "schema_version": 1,
        "target": "codex",
        "version": "0.1.0",
        "release_binding": binding,
        "CANDIDATE_OFFLINE": "PASS",
    }
    offline["evidence_body_sha256"] = evidence_body_sha256(offline)
    evidence_path = candidate / "acceptance-evidence.json"
    evidence_path.write_bytes(_json_bytes(offline))
    bind_acceptance_evidence(
        candidate / "release-manifest.json",
        evidence_path,
    )
    return candidate, binding


def _final_evidence(
    path: Path,
    binding: dict[str, object],
    *,
    failed_gate: str | None = None,
) -> Path:
    evidence = {
        "schema_version": 1,
        "target": "codex",
        "version": str(binding["version"]),
        "release_binding": binding,
        **{gate: "PASS" for gate in REQUIRED_FULL_RELEASE_GATES},
        "RELEASE_INTEGRITY": "PASS",
        "PROGRAM_RELEASE": "1/3",
    }
    if failed_gate:
        evidence[failed_gate] = "NOT_PASS"
    evidence["evidence_body_sha256"] = evidence_body_sha256(evidence)
    path.write_bytes(_json_bytes(evidence))
    return path


def test_promotion_reuses_exact_candidate_zip_bytes(repo_root, tmp_path):
    candidate, binding = _candidate(repo_root, tmp_path)
    source_zip = candidate / "codex-base-0.1.0.zip"
    source_bytes = source_zip.read_bytes()
    final = _final_evidence(
        tmp_path / "final-evidence.json",
        binding,
    )

    result = promote_candidate(candidate, final, tmp_path / "stable")

    assert result.zip_path.read_bytes() == source_bytes
    assert result.zip_sha256 == hashlib.sha256(source_bytes).hexdigest()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["channel"] == "stable"
    assert manifest["acceptance_evidence_sha256"] == hashlib.sha256(
        final.read_bytes()
    ).hexdigest()
    assert len(manifest["promoted_from_candidate_manifest_sha256"]) == 64


def test_codex_package_acceptance_matches_employee_installer_contract(
    repo_root, tmp_path
):
    candidate, binding = _candidate(repo_root, tmp_path)
    final = _final_evidence(
        tmp_path / "final-evidence.json",
        binding,
    )
    stable = promote_candidate(candidate, final, tmp_path / "stable")

    output = stable.manifest_path.parent / "package-acceptance.json"
    acceptance = create_package_acceptance(
        stable.manifest_path,
        stable.evidence_path,
        output,
    )

    assert json.loads(output.read_text(encoding="utf-8")) == acceptance
    assert acceptance["target"] == "codex"
    assert acceptance["package_acceptance"] == "PASS"
    assert acceptance["client"] == {
        "id": "codex-cli",
        "supported_version": "0.146.0-alpha.3.1",
    }
    assert acceptance["asset"]["sha256"] == stable.zip_sha256
    assert acceptance["immutable_release"] is True
    assert acceptance["release_attestation"] is True


def test_codex_package_acceptance_requires_release_integrity(
    repo_root, tmp_path
):
    candidate, binding = _candidate(repo_root, tmp_path)
    final = _final_evidence(
        tmp_path / "final-evidence.json",
        binding,
    )
    evidence = json.loads(final.read_text(encoding="utf-8"))
    evidence["RELEASE_INTEGRITY"] = "NOT_PASS"
    evidence["evidence_body_sha256"] = evidence_body_sha256(evidence)
    final.write_bytes(_json_bytes(evidence))
    stable = promote_candidate(candidate, final, tmp_path / "stable")

    with pytest.raises(ValueError, match="release integrity"):
        create_package_acceptance(
            stable.manifest_path,
            stable.evidence_path,
            stable.manifest_path.parent / "package-acceptance.json",
        )


def test_codex_package_acceptance_rejects_wrong_evidence_identity(
    repo_root, tmp_path
):
    candidate, binding = _candidate(repo_root, tmp_path)
    final = _final_evidence(
        tmp_path / "final-evidence.json",
        binding,
    )
    evidence = json.loads(final.read_text(encoding="utf-8"))
    evidence["target"] = "other"
    evidence["evidence_body_sha256"] = evidence_body_sha256(evidence)
    final.write_bytes(_json_bytes(evidence))

    with pytest.raises(ValueError, match="identity"):
        promote_candidate(candidate, final, tmp_path / "stable")


@pytest.mark.parametrize(
    "gate",
    ["MATCHED_AB", "CODEX_CANARY", "FULL_RELEASE_CODEX"],
)
def test_promotion_fails_closed_when_required_gate_is_missing_or_not_pass(
    repo_root, tmp_path, gate
):
    candidate, binding = _candidate(repo_root, tmp_path)
    final = _final_evidence(
        tmp_path / "final-evidence.json",
        binding,
        failed_gate=gate,
    )

    with pytest.raises(ValueError, match=gate):
        promote_candidate(candidate, final, tmp_path / "stable")

    assert not (tmp_path / "stable").exists()
