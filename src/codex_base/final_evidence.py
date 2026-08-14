from __future__ import annotations

import hashlib
import json
from typing import Any

from .acceptance import evidence_body_sha256
from .canary import EXPECTED_PHASES
from .matched_ab import (
    DISABLED_TOOL_FEATURES,
    INHERITABLE_PACKAGE_CHANGES,
    MAX_INPUT_TOKENS,
    MIN_MEDIAN_INPUT_REDUCTION,
    MODEL,
    REASONING_EFFORT,
    SUPPORTED_CLIENT,
)


OFFLINE_GATES = (
    "FOUNDATION_SYNTHETIC",
    "OFFLINE_CODEX_CONTENT",
    "STATIC_TOKEN_ACCEPTANCE",
    "CODEX_OFFLINE_INTEGRATION",
    "CODEX_TESTS",
    "CANDIDATE_OFFLINE",
)
LEGACY_SYNC_BOOTSTRAP_CONTRACT = {
    "mode": "CONSUMER_VERIFIED_BEFORE_EVIDENCE",
    "legacy_updater": "codex-v0.1.1",
    "required_checks": [
        "gh release verify",
        "gh release verify-asset",
        "gh attestation verify",
    ],
}


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _valid_body(evidence: dict[str, Any]) -> bool:
    return evidence.get("evidence_body_sha256") == evidence_body_sha256(
        evidence
    )


def _source_record(evidence: dict[str, Any]) -> dict[str, object]:
    payload = _json_bytes(evidence)
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def _validate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    binding = candidate.get("release_binding")
    if (
        candidate.get("schema_version") != 1
        or candidate.get("target") != "codex"
        or not isinstance(binding, dict)
        or binding.get("target") != "codex"
        or candidate.get("version") != binding.get("version")
        or any(candidate.get(gate) != "PASS" for gate in OFFLINE_GATES)
        or not _valid_body(candidate)
    ):
        raise ValueError("candidate offline evidence is invalid")
    asset = binding.get("asset")
    if not isinstance(asset, dict):
        raise ValueError("candidate offline evidence asset is invalid")
    return binding


def _validate_matched(
    matched: dict[str, Any],
    binding: dict[str, Any],
) -> None:
    client = matched.get("client")
    package = matched.get("candidate_package")
    tools = matched.get("tools")
    privacy = matched.get("privacy")
    metrics = matched.get("metrics")
    runs = matched.get("runs")
    expected = [
        ("legacy", "hello"),
        ("candidate", "hello"),
        ("legacy", "capabilities"),
        ("candidate", "capabilities"),
    ]
    run_identity = (
        [
            (row.get("variant"), row.get("prompt_id"))
            for row in runs
            if isinstance(row, dict)
        ]
        if isinstance(runs, list)
        else []
    )
    usages_valid = (
        isinstance(runs, list)
        and len(runs) == 4
        and all(
            isinstance(row, dict)
            and isinstance(row.get("usage"), dict)
            and isinstance(row["usage"].get("input_tokens"), int)
            and not isinstance(row["usage"].get("input_tokens"), bool)
            and 0 <= row["usage"]["input_tokens"] <= MAX_INPUT_TOKENS
            and row.get("tool_events") == 0
            for row in runs
        )
    )
    inheritance = matched.get("inheritance")
    changed_paths = (
        inheritance.get("changed_paths")
        if isinstance(inheritance, dict)
        else None
    )
    source_digest = (
        str(inheritance.get("source_evidence_body_sha256") or "")
        if isinstance(inheritance, dict)
        else ""
    )
    evaluated_package = matched.get("evaluated_package")
    evaluated_digest = (
        str(evaluated_package.get("sha256") or "")
        if isinstance(evaluated_package, dict)
        else ""
    )
    previous_model_digest = (
        str(inheritance.get("previous_model_surface_sha256") or "")
        if isinstance(inheritance, dict)
        else ""
    )
    candidate_model_digest = (
        str(inheritance.get("candidate_model_surface_sha256") or "")
        if isinstance(inheritance, dict)
        else ""
    )
    direct_calls = (
        matched.get("evidence_mode") is None
        and matched.get("calls_authorized") == 4
        and matched.get("calls_completed") == 4
    )
    inherited_calls = (
        matched.get("evidence_mode") == "INHERITED_ZERO_CALL"
        and matched.get("calls_authorized") == 0
        and matched.get("calls_completed") == 0
        and matched.get("inherited_calls") == 4
        and matched.get("repeat_authorized") is False
        and isinstance(evaluated_package, dict)
        and len(evaluated_digest) == 64
        and all(
            character in "0123456789abcdef"
            for character in evaluated_digest
        )
        and isinstance(evaluated_package.get("bytes"), int)
        and not isinstance(evaluated_package.get("bytes"), bool)
        and evaluated_package["bytes"] > 0
        and isinstance(inheritance, dict)
        and len(source_digest) == 64
        and all(character in "0123456789abcdef" for character in source_digest)
        and len(previous_model_digest) == 64
        and all(
            character in "0123456789abcdef"
            for character in previous_model_digest
        )
        and previous_model_digest == candidate_model_digest
        and isinstance(changed_paths, list)
        and bool(changed_paths)
        and changed_paths == sorted(changed_paths)
        and all(
            path in INHERITABLE_PACKAGE_CHANGES for path in changed_paths
        )
        and inheritance.get("new_paid_calls") == 0
    )
    valid = (
        matched.get("schema_version") == 1
        and matched.get("MATCHED_AB") == "PASS"
        and (direct_calls or inherited_calls)
        and client
        == {
            "id": "codex-cli",
            "version": SUPPORTED_CLIENT,
        }
        and matched.get("model") == MODEL
        and matched.get("reasoning_effort") == REASONING_EFFORT
        and isinstance(package, dict)
        and isinstance(binding.get("asset"), dict)
        and package
        == {
            "sha256": binding["asset"].get("sha256"),
            "bytes": binding["asset"].get("bytes"),
        }
        and isinstance(tools, dict)
        and tools.get("disabled_features")
        == list(DISABLED_TOOL_FEATURES)
        and tools.get("web_search") == "disabled"
        and tools.get("unexpected_tool_events") == 0
        and isinstance(privacy, dict)
        and privacy.get("prompt_text_included") is False
        and privacy.get("response_text_included") is False
        and privacy.get("credentials_included") is False
        and privacy.get("personal_data_included") is False
        and isinstance(metrics, dict)
        and isinstance(metrics.get("median_input_reduction"), (int, float))
        and metrics["median_input_reduction"] >= MIN_MEDIAN_INPUT_REDUCTION
        and run_identity == expected
        and usages_valid
        and _valid_body(matched)
    )
    if not valid:
        raise ValueError("matched A/B evidence is invalid or unbound")


def _validate_canary(
    canary: dict[str, Any],
    binding: dict[str, Any],
) -> None:
    valid = (
        canary.get("schema_version") == 1
        and canary.get("target") == "codex"
        and canary.get("version") == binding.get("version")
        and canary.get("release_binding") == binding
        and canary.get("CODEX_CANARY") == "PASS"
        and canary.get("model_requests") == 0
        and canary.get("phases") == EXPECTED_PHASES
        and canary.get("discovery") == {"agents": 16, "skills": 40}
        and isinstance(canary.get("rollback"), dict)
        and canary["rollback"].get("byte_identical") is True
        and canary.get("credentials_included") is False
        and canary.get("personal_data_included") is False
        and _valid_body(canary)
    )
    if not valid:
        raise ValueError("Codex canary evidence is invalid or unbound")


def compose_final_evidence(
    *,
    candidate: dict[str, Any],
    matched_ab: dict[str, Any],
    canary: dict[str, Any],
    legacy_sync_bootstrap: bool = False,
) -> dict[str, Any]:
    """Compose fail-closed pre-publication FULL evidence from three inputs."""

    binding = _validate_candidate(candidate)
    _validate_matched(matched_ab, binding)
    _validate_canary(canary, binding)
    final = dict(candidate)
    final.pop("evidence_body_sha256", None)
    release_integrity = "PASS" if legacy_sync_bootstrap else "PENDING_PUBLICATION"
    final.update(
        {
            "MATCHED_AB": "PASS",
            "CODEX_CANARY": "PASS",
            "FULL_RELEASE_CODEX": "PASS",
            "PROGRAM_RELEASE": "1/3",
            "RELEASE_INTEGRITY": release_integrity,
            "matched_ab_metrics": matched_ab["metrics"],
            "evidence_sources": {
                "candidate_offline": _source_record(candidate),
                "matched_ab": _source_record(matched_ab),
                "canary": _source_record(canary),
            },
            "release_permissions": {
                "paid_matched_ab": "COMPLETED_AUTHORIZED_FOUR",
                "hub_canary": "PASS",
                "stable_release": "AUTHORIZED_AFTER_SAME_BYTES_PROMOTION",
            },
            "limitations": [
                "Release integrity is pending immutable publication and GitHub attestation verification.",
                "package-acceptance.json must be created only from post-publication release-verification.json.",
                "No A/B repeat or matrix expansion is authorized.",
            ],
        }
    )
    if legacy_sync_bootstrap:
        final["release_integrity_contract"] = dict(
            LEGACY_SYNC_BOOTSTRAP_CONTRACT
        )
    final["evidence_body_sha256"] = evidence_body_sha256(final)
    return final
