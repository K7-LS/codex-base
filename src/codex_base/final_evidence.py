from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .acceptance import evidence_body_sha256
from .foundation_evidence import validate_foundation_engine
from .canary import EXPECTED_PHASES
from .core_acceptance import (
    ACCEPTANCE_PROTOCOL, MATCHED_AB_NOT_REQUIRED_REASON,
    package_client, package_discovery, package_foundation_sha256, validate_core_behavior,
    validate_current_wire_keys,
)
from .matched_ab import (
    DISABLED_TOOL_FEATURES,
    INHERITABLE_PACKAGE_CHANGES,
    MAX_INPUT_TOKENS,
    MATCHED_AB_SCHEMA_VERSION,
    MIN_MEDIAN_INPUT_REDUCTION,
    validate_matched_ab_benchmark,
    MODEL,
    REASONING_EFFORT,
    SUPPORTED_CLIENT,
)


HISTORICAL_OFFLINE_GATES = (
    "FOUNDATION_SYNTHETIC",
    "OFFLINE_CODEX_CONTENT",
    "STATIC_TOKEN_ACCEPTANCE",
    "CODEX_OFFLINE_INTEGRATION",
    "CODEX_TESTS",
    "CANDIDATE_OFFLINE",
)
OFFLINE_GATES = ("FOUNDATION_ENGINE_ACCEPTANCE",) + HISTORICAL_OFFLINE_GATES[1:]
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


def _validate_candidate(candidate: dict[str, Any], *, historical: bool = False) -> dict[str, Any]:
    binding = candidate.get("release_binding")
    if (
        candidate.get("schema_version") != 1
        or candidate.get("target") != "codex"
        or not isinstance(binding, dict)
        or binding.get("target") != "codex"
        or candidate.get("version") != binding.get("version")
        or any(candidate.get(gate) != "PASS" for gate in (HISTORICAL_OFFLINE_GATES if historical else OFFLINE_GATES))
        or (not historical and candidate.get("FOUNDATION_SYNTHETIC") != "NOT_RUN")
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
    # Fail-open: сборка возвращала FULL_RELEASE_CODEX=PASS даже после
    # удаления matched["surfaces"] и подмены benchmark. Контракт бенчмарка и
    # digest контрольной поверхности проверяются первыми и жёстко.
    validate_matched_ab_benchmark(matched)
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
        matched.get("schema_version") == MATCHED_AB_SCHEMA_VERSION
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
    package_path: Path | None = None,
) -> None:
    if not isinstance(canary, dict):
        raise ValueError("Codex canary evidence is missing")
    expected_discovery = package_discovery(package_path, binding) if package_path else {"agents": 16, "skills": 41}
    valid = (
        canary.get("schema_version") == 1
        and canary.get("target") == "codex"
        and canary.get("version") == binding.get("version")
        and canary.get("release_binding") == binding
        and canary.get("CODEX_CANARY") == "PASS"
        and canary.get("model_requests") == 0
        and canary.get("phases") == EXPECTED_PHASES
        and canary.get("discovery") == expected_discovery
        and (package_path is None or (canary.get("client") == package_client(package_path)
                                     and canary.get("canary_protocol") == "package-bound-v1"))
        and isinstance(canary.get("rollback"), dict)
        and canary["rollback"].get("byte_identical") is True
        and canary.get("credentials_included") is False
        and canary.get("personal_data_included") is False
        and _valid_body(canary)
    )
    if not valid:
        raise ValueError("Codex canary evidence is invalid or unbound")
    if package_path is not None:
        rollback = canary["rollback"]
        before = rollback.get("before_surface_sha256")
        preserved = canary.get("preserved_files")
        if (not isinstance(before, str) or len(before) != 64 or any(c not in "0123456789abcdef" for c in before)
            or before != rollback.get("after_surface_sha256")
            or not isinstance(preserved, int) or isinstance(preserved, bool) or preserved < 7
            or canary.get("foundation_sha256") != package_foundation_sha256(package_path, binding)):
            raise ValueError("Codex canary rollback or Foundation binding differs")


def validate_historical_inputs(*, candidate: dict, matched_ab: dict, canary: dict) -> dict:
    """Read-only validation of the original experiment. Never promotion authority."""
    binding = _validate_candidate(candidate, historical=True)
    _validate_matched(matched_ab, binding)
    _validate_canary(canary, binding)
    return {"HISTORICAL_INPUTS": "PASS", "release_eligible": False}


def compose_final_evidence(
    *,
    candidate: dict[str, Any],
    canary: dict[str, Any],
    core_behavior: dict[str, Any] | None = None,
    package_path: Path | None = None,
    artifact_root: Path | None = None,
    legacy_sync_bootstrap: bool = False,
) -> dict[str, Any]:
    """Compose current evidence; historical A/B remains a separate benchmark."""

    binding = _validate_candidate(candidate)
    if "core_behavior" in candidate:
        raise ValueError("obsolete core_behavior wire key collides with the PowerShell verdict key")
    if package_path is None or artifact_root is None:
        raise ValueError("core behavior evidence requires package and artifact paths")
    validate_foundation_engine(candidate.get("foundation"), candidate.get("foundation_artifacts"),
                               binding, package_path=package_path)
    validate_core_behavior(core_behavior, binding, package_path=package_path, artifact_root=artifact_root)
    _validate_canary(canary, binding, package_path)
    final = dict(candidate)
    final.pop("evidence_body_sha256", None)
    final.pop("matched_ab_metrics", None)
    final.pop("matched_ab_benchmark", None)
    release_integrity = "PASS" if legacy_sync_bootstrap else "PENDING_PUBLICATION"
    final.update(
        {
            "acceptance_protocol": ACCEPTANCE_PROTOCOL,
            "MATCHED_AB": "NOT_REQUIRED",
            "matched_ab_not_required_reason": MATCHED_AB_NOT_REQUIRED_REASON,
            "CODEX_CANARY": "PASS",
            "canary_evidence": canary,
            "CORE_BEHAVIOR": "PASS",
            "core_behavior_evidence": core_behavior,
            "FULL_RELEASE_CODEX": "PASS",
            "PROGRAM_RELEASE": "1/3",
            "RELEASE_INTEGRITY": release_integrity,
            "evidence_sources": {
                "candidate_offline": _source_record(candidate),
                "canary": _source_record(canary),
                "core_behavior_evidence": _source_record(core_behavior),
            },
            "release_permissions": {
                "paid_matched_ab": "NOT_REQUIRED_HISTORICAL_BENCHMARK",
                "hub_canary": "PASS",
                "stable_release": "REQUIRES_SEPARATE_OWNER_AUTHORIZATION",
            },
            "limitations": [
                "Release integrity is pending immutable publication and GitHub attestation verification.",
                "package-acceptance.json must be created only from post-publication release-verification.json.",
                "Historical matched A/B is neither required nor claimed as PASS by this protocol.",
                "Core evidence establishes conformance coverage, not reliability or execution authenticity.",
            ],
        }
    )
    if legacy_sync_bootstrap:
        final["release_integrity_contract"] = dict(
            LEGACY_SYNC_BOOTSTRAP_CONTRACT
        )
    final["evidence_body_sha256"] = evidence_body_sha256(final)
    validate_current_wire_keys(final)
    return final
