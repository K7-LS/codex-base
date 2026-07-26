from __future__ import annotations

import json

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


def test_tracked_token_report_matches_current_hot_and_warm_surfaces(repo_root):
    expected = audit_static_context(repo_root)
    tracked = json.loads(
        (repo_root / "reports" / "static-token-audit.json").read_text(
            encoding="utf-8"
        )
    )
    assert tracked == expected

    docs = (repo_root / "docs" / "INSTALL-AND-NETWORK.md").read_text(
        encoding="utf-8"
    )
    candidate = expected["candidate"]
    reduction = expected["results"]["base_controlled_startup_reduction"] * 100
    assert f"{candidate['estimated_tokens']:,}" in docs
    assert f"{reduction:.2f}%" in docs
