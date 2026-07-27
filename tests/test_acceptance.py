from __future__ import annotations

import json
import zipfile
from pathlib import Path

from codex_base.acceptance import (
    evidence_body_sha256,
    scan_automatic_network_surfaces,
    scan_secrets,
    validate_structured_files,
    write_acceptance_evidence,
)


def _release_manifest() -> dict[str, object]:
    return {
        "target": "codex",
        "version": "0.1.0",
        "tag": "codex-v0.1.0",
        "asset": {
            "name": "codex-base-0.1.0.zip",
            "sha256": "1" * 64,
            "bytes": 1,
        },
        "package_manifest_sha256": "2" * 64,
        "components_lock_sha256": "3" * 64,
        "source": {
            "repository": "https://github.com/example/codex-base",
            "commit": "4" * 40,
            "tree": "5" * 40,
            "transformation": "codex-native-v1",
        },
        "foundation_engine_version": "0.1.0",
        "foundation_engine_manifest_sha256": "6" * 64,
    }


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


def test_secret_scan_covers_unknown_binary_suffix_and_archive_members(
    tmp_path,
):
    key = ("sk-" + ("A" * 30)).encode()
    (tmp_path / "opaque.bin").write_bytes(b"\x00" + key + b"\x00")
    with zipfile.ZipFile(tmp_path / "artifact.pkg", "w") as archive:
        archive.writestr("nested/value.txt", key)

    result = scan_secrets(tmp_path)

    assert result["status"] == "NOT_PASS"
    assert {finding["path"] for finding in result["findings"]} == {
        "artifact.pkg",
        "opaque.bin",
    }


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
        release_manifest=_release_manifest(),
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
    assert evidence["release_permissions"]["paid_matched_ab"] == (
        "APPROVED_EXACTLY_FOUR_NOT_RUN"
    )
    assert evidence["release_permissions"]["hub_canary"] == (
        "APPROVED_NOT_RUN"
    )
    assert evidence["evidence_body_sha256"] == evidence_body_sha256(
        evidence
    )
    assert evidence["release_binding"]["asset"]["sha256"] == "1" * 64


def test_acceptance_never_promotes_from_missing_foundation_evidence(
    repo_root, tmp_path
):
    evidence = write_acceptance_evidence(
        repo_root=repo_root,
        destination=tmp_path / "acceptance-evidence.json",
        version="0.1.0",
        foundation_evidence=None,
        release_manifest=_release_manifest(),
    )

    assert evidence["FOUNDATION_SYNTHETIC"] == "NOT_RUN"
    assert evidence["OFFLINE_CODEX_CONTENT"] == "PASS"
    assert evidence["FULL_RELEASE_CODEX"] == "NOT_PASS"
