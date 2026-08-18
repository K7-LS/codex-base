from __future__ import annotations

import hashlib

import pytest

from codex_base.acceptance import evidence_body_sha256
from codex_base.canary import build_canary_evidence
from codex_base.final_evidence import compose_final_evidence
from codex_base.matched_ab import summarize_results


def _binding() -> dict[str, object]:
    return {
        "target": "codex",
        "version": "0.1.1",
        "tag": "codex-v0.1.1",
        "asset": {
            "name": "codex-base-0.1.1.zip",
            "sha256": "a" * 64,
            "bytes": 123,
        },
        "package_manifest_sha256": "b" * 64,
        "components_lock_sha256": "c" * 64,
        "source": {
            "repository": "https://github.com/daniileliseev1337/codex-base",
            "commit": "d" * 40,
            "tree": "e" * 40,
            "transformation": "codex-native-v1",
        },
        "foundation_engine_version": "0.2.1",
        "foundation_engine_manifest_sha256": "f" * 64,
    }


def _candidate(binding: dict[str, object]) -> dict[str, object]:
    evidence = {
        "schema_version": 1,
        "target": "codex",
        "version": "0.1.1",
        "release_binding": binding,
        "FOUNDATION_SYNTHETIC": "PASS",
        "OFFLINE_CODEX_CONTENT": "PASS",
        "STATIC_TOKEN_ACCEPTANCE": "PASS",
        "CODEX_OFFLINE_INTEGRATION": "PASS",
        "CODEX_TESTS": "PASS",
        "CANDIDATE_OFFLINE": "PASS",
        "MATCHED_AB": "NOT_RUN",
        "CODEX_CANARY": "NOT_RUN",
        "FULL_RELEASE_CODEX": "NOT_PASS",
        "PROGRAM_RELEASE": "0/3",
    }
    evidence["evidence_body_sha256"] = evidence_body_sha256(evidence)
    return evidence


def _matched(binding: dict[str, object]) -> dict[str, object]:
    def usage(tokens: int) -> dict[str, int]:
        return {
            "input_tokens": tokens,
            "cached_input_tokens": 0,
            "output_tokens": 10,
            "reasoning_output_tokens": 0,
        }

    rows = []
    for variant, prompt_id, tokens in (
        ("legacy", "hello", 80000),
        ("candidate", "hello", 30000),
        ("legacy", "capabilities", 100000),
        ("candidate", "capabilities", 40000),
    ):
        rows.append(
            {
                "variant": variant,
                "prompt_id": prompt_id,
                "usage": usage(tokens),
                "result_sha256": hashlib.sha256(
                    f"{variant}-{prompt_id}".encode()
                ).hexdigest(),
            }
        )
    return summarize_results(
        rows,
        client_version="0.146.0-alpha.3.1",
        legacy_surface_sha256="1" * 64,
        candidate_surface_sha256="2" * 64,
        candidate_package_sha256=binding["asset"]["sha256"],
        candidate_package_bytes=binding["asset"]["bytes"],
    )


def _inherited_matched(binding: dict[str, object]) -> dict[str, object]:
    evidence = _matched(binding)
    evidence.pop("evidence_body_sha256")
    evidence.update(
        {
            "evidence_mode": "INHERITED_ZERO_CALL",
            "calls_authorized": 0,
            "calls_completed": 0,
            "inherited_calls": 4,
            "repeat_authorized": False,
            "evaluated_package": {
                "sha256": "9" * 64,
                "bytes": 122,
            },
            "inheritance": {
                "source_evidence_body_sha256": "8" * 64,
                "previous_model_surface_sha256": "7" * 64,
                "candidate_model_surface_sha256": "7" * 64,
                "changed_paths": [
                    ".agents/skills/sync-base/sync-policy.json",
                    ".codex/base/VERSION",
                    ".codex/base/components.lock.json",
                    "package-manifest.json",
                ],
                "new_paid_calls": 0,
            },
        }
    )
    evidence["evidence_body_sha256"] = evidence_body_sha256(evidence)
    return evidence


def _canary(binding: dict[str, object]) -> dict[str, object]:
    return build_canary_evidence(
        release_binding=binding,
        client_version="0.146.0-alpha.3.1",
        foundation_sha256="3" * 64,
        before_surface_sha256="4" * 64,
        after_rollback_surface_sha256="4" * 64,
        phase_statuses={
            "plan": "READY",
            "install": "CANONICAL_WITH_LOCAL_EXCEPTIONS",
            "doctor": "CANONICAL_WITH_LOCAL_EXCEPTIONS",
            "inventory": "INVENTORIED",
            "rollback": "ROLLED_BACK",
        },
        discovery={"agents": 16, "skills": 41},
        preserved_files=8,
    )


def test_final_evidence_is_composed_only_from_bound_pass_evidence():
    binding = _binding()
    final = compose_final_evidence(
        candidate=_candidate(binding),
        matched_ab=_matched(binding),
        canary=_canary(binding),
    )

    assert final["FULL_RELEASE_CODEX"] == "PASS"
    assert final["PROGRAM_RELEASE"] == "1/3"
    assert final["RELEASE_INTEGRITY"] == "PENDING_PUBLICATION"
    assert final["MATCHED_AB"] == "PASS"
    assert final["CODEX_CANARY"] == "PASS"
    assert (
        final["evidence_body_sha256"] == evidence_body_sha256(final)
    )
    assert set(final["evidence_sources"]) == {
        "candidate_offline",
        "matched_ab",
        "canary",
    }


def test_legacy_sync_bootstrap_declares_consumer_verified_integrity_contract():
    binding = _binding()

    final = compose_final_evidence(
        candidate=_candidate(binding),
        matched_ab=_matched(binding),
        canary=_canary(binding),
        legacy_sync_bootstrap=True,
    )

    assert final["RELEASE_INTEGRITY"] == "PASS"
    assert final["release_integrity_contract"] == {
        "mode": "CONSUMER_VERIFIED_BEFORE_EVIDENCE",
        "legacy_updater": "codex-v0.1.1",
        "required_checks": [
            "gh release verify",
            "gh release verify-asset",
            "gh attestation verify",
        ],
    }
    assert final["evidence_body_sha256"] == evidence_body_sha256(final)


def test_final_evidence_accepts_zero_call_inheritance_for_equal_model_surface():
    binding = _binding()
    matched = _inherited_matched(binding)

    final = compose_final_evidence(
        candidate=_candidate(binding),
        matched_ab=matched,
        canary=_canary(binding),
    )

    assert final["MATCHED_AB"] == "PASS"
    assert matched["calls_completed"] == 0
    assert matched["inherited_calls"] == 4
    assert final["matched_ab_metrics"] == matched["metrics"]


def test_final_evidence_rejects_inheritance_with_changed_model_surface():
    binding = _binding()
    matched = _inherited_matched(binding)
    matched["inheritance"]["candidate_model_surface_sha256"] = "6" * 64
    matched["evidence_body_sha256"] = evidence_body_sha256(matched)

    with pytest.raises(ValueError, match="matched A/B evidence"):
        compose_final_evidence(
            candidate=_candidate(binding),
            matched_ab=matched,
            canary=_canary(binding),
        )


def test_final_evidence_rejects_missing_inherited_model_surface_digest():
    binding = _binding()
    matched = _inherited_matched(binding)
    matched["inheritance"]["previous_model_surface_sha256"] = ""
    matched["inheritance"]["candidate_model_surface_sha256"] = ""
    matched["evidence_body_sha256"] = evidence_body_sha256(matched)

    with pytest.raises(ValueError, match="matched A/B evidence"):
        compose_final_evidence(
            candidate=_candidate(binding),
            matched_ab=matched,
            canary=_canary(binding),
        )


@pytest.mark.parametrize("tamper", ["candidate", "matched", "canary"])
def test_final_evidence_rejects_tampered_or_unbound_inputs(tamper: str):
    binding = _binding()
    candidate = _candidate(binding)
    matched = _matched(binding)
    canary = _canary(binding)
    if tamper == "candidate":
        candidate["CANDIDATE_OFFLINE"] = "NOT_PASS"
    elif tamper == "matched":
        matched["candidate_package"]["sha256"] = "9" * 64
        matched["evidence_body_sha256"] = evidence_body_sha256(matched)
    else:
        canary["release_binding"] = {**binding, "version": "9.9.9"}
        canary["evidence_body_sha256"] = evidence_body_sha256(canary)

    with pytest.raises(ValueError, match="evidence"):
        compose_final_evidence(
            candidate=candidate,
            matched_ab=matched,
            canary=canary,
        )
