from __future__ import annotations

import json
from pathlib import Path

from codex_base.acceptance import (
    scan_automatic_network_surfaces,
    scan_secrets,
    validate_structured_files,
    write_acceptance_evidence,
)


def test_all_runtime_json_toml_and_yaml_files_parse(repo_root):
    result = validate_structured_files(repo_root)

    assert result["status"] == "PASS"
    assert result["counts"]["json"] > 0
    assert result["counts"]["toml"] >= 17
    assert result["counts"]["yaml"] >= 2
    assert result["errors"] == []


def test_repository_contains_no_embedded_secrets(repo_root):
    result = scan_secrets(repo_root)

    assert result["status"] == "PASS"
    assert result["findings"] == []


def test_automatic_network_is_one_way_and_github_read_only(repo_root):
    result = scan_automatic_network_surfaces(repo_root)

    assert result["status"] == "PASS"
    assert result["automatic_hosts"] == ["api.github.com"]
    assert result["reverse_flow_findings"] == []
    assert result["permitted_gh_operations"] == [
        "release download",
        "release list",
        "release verify",
        "release verify-asset",
    ]


def test_acceptance_evidence_is_fail_closed_until_paid_ab_and_canary(
    repo_root, tmp_path
):
    foundation = {
        "FOUNDATION_SYNTHETIC": "PASS",
        "engine_version": "0.1.0",
        "ps7": {"passed": 1, "failed": 0},
        "ps51": {"passed": 1, "failed": 0},
    }
    path = tmp_path / "acceptance-evidence.json"
    evidence = write_acceptance_evidence(
        repo_root=repo_root,
        destination=path,
        version="0.1.0",
        foundation_evidence=foundation,
    )

    assert json.loads(path.read_text(encoding="utf-8")) == evidence
    assert evidence["OFFLINE_CODEX_CONTENT"] == "PASS"
    assert evidence["FOUNDATION_SYNTHETIC"] == "PASS"
    assert evidence["STATIC_TOKEN_ACCEPTANCE"] == "PASS"
    assert evidence["MATCHED_AB"] == "NOT_RUN"
    assert evidence["CODEX_CANARY"] == "NOT_RUN"
    assert evidence["FULL_RELEASE_CODEX"] == "NOT_PASS"
    assert evidence["PROGRAM_RELEASE"] == "0/3"
    assert evidence["release_permissions"]["stable_release"] == "BLOCKED"


def test_acceptance_never_promotes_from_missing_foundation_evidence(
    repo_root, tmp_path
):
    evidence = write_acceptance_evidence(
        repo_root=repo_root,
        destination=tmp_path / "acceptance-evidence.json",
        version="0.1.0",
        foundation_evidence=None,
    )

    assert evidence["FOUNDATION_SYNTHETIC"] == "NOT_RUN"
    assert evidence["OFFLINE_CODEX_CONTENT"] == "PASS"
    assert evidence["FULL_RELEASE_CODEX"] == "NOT_PASS"
