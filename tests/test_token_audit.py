from __future__ import annotations

from codex_base.token_audit import audit_static_context


def test_static_startup_context_reduction_exceeds_release_threshold(repo_root):
    report = audit_static_context(repo_root)

    assert report["results"]["STATIC_TOKEN_ACCEPTANCE"] == "PASS"
    assert report["results"]["base_controlled_startup_reduction"] >= 0.70
    assert report["candidate"]["cold_payload_in_startup"] is False
    assert report["candidate"]["surfaces"]["agents_discovery"]["count"] == 16
    assert (
        report["candidate"]["surfaces"]["skills_discovery"]["capability_skills"]
        == 37
    )
    assert report["candidate"]["surfaces"]["skills_discovery"]["control_skills"] == 1


def test_static_audit_never_claims_paid_matched_ab(repo_root):
    report = audit_static_context(repo_root)

    assert report["results"]["MATCHED_AB"] == "NOT_RUN"
    assert report["thresholds"]["matched_ab_total_input_reduction_min"] == 0.25
