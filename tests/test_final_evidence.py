from __future__ import annotations

import copy

import hashlib
import json
import shutil
import subprocess

import pytest

from codex_base.acceptance import evidence_body_sha256
from core_evidence_support import minimal_package, core_arguments
from codex_base.canary import build_canary_evidence
from codex_base.final_evidence import _validate_matched, compose_final_evidence, validate_historical_inputs
from codex_base.core_acceptance import package_discovery, package_foundation_sha256
from codex_base.matched_ab import LEGACY_SURFACE_SHA256, summarize_results


def _binding(tmp_path) -> dict[str, object]:
    binding = {
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
            "repository": "https://github.com/K7-LS/codex-base",
            "commit": "d" * 40,
            "tree": "e" * 40,
            "transformation": "codex-native-independent-v2",
        },
        "foundation_engine_version": "0.2.1",
        "foundation_engine_manifest_sha256": "f" * 64,
    }
    minimal_package(tmp_path, binding)
    return binding


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
        legacy_surface_sha256=LEGACY_SURFACE_SHA256,
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


def _canary(binding: dict[str, object], package_path=None) -> dict[str, object]:
    return build_canary_evidence(
        release_binding=binding,
        client_version="0.146.0-alpha.3.1",
        foundation_sha256=package_foundation_sha256(package_path, binding) if package_path else "3" * 64,
        before_surface_sha256="4" * 64,
        after_rollback_surface_sha256="4" * 64,
        phase_statuses={
            "plan": "READY",
            "install": "CANONICAL_WITH_LOCAL_EXCEPTIONS",
            "doctor": "CANONICAL_WITH_LOCAL_EXCEPTIONS",
            "inventory": "INVENTORIED",
            "rollback": "ROLLED_BACK",
        },
        discovery=package_discovery(package_path, binding) if package_path else {"agents": 16, "skills": 41},
        package_path=package_path,
        preserved_files=8,
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_current_composition_needs_no_historical_model_call(tmp_path, legacy):
    binding = _binding(tmp_path)
    args = core_arguments(binding, tmp_path)
    final = compose_final_evidence(candidate=_candidate(binding),
                                   canary=_canary(binding, args["package_path"]),
                                   legacy_sync_bootstrap=legacy, **args)
    assert final["FULL_RELEASE_CODEX"] == "PASS"
    assert final["CORE_BEHAVIOR"] == "PASS"
    assert final["MATCHED_AB"] == "NOT_REQUIRED"
    assert final["acceptance_protocol"] == "professional-core-v1"
    assert "matched_ab" not in final["evidence_sources"]
    assert "matched_ab_metrics" not in final
    assert final["RELEASE_INTEGRITY"] == ("PASS" if legacy else "PENDING_PUBLICATION")
    assert final["evidence_body_sha256"] == evidence_body_sha256(final)


@pytest.mark.parametrize("shell", ["pwsh", "powershell"])
def test_real_composition_round_trips_windows_json_without_case_collision(tmp_path, shell):
    executable = shutil.which(shell)
    if executable is None:
        pytest.skip(f"{shell} unavailable")
    binding = _binding(tmp_path)
    args = core_arguments(binding, tmp_path)
    final = compose_final_evidence(candidate=_candidate(binding),
                                  canary=_canary(binding, args["package_path"]), **args)
    path = tmp_path / "composed.json"
    path.write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
    script = tmp_path / "read.ps1"
    script.write_text("param([string]$Path)\n$ErrorActionPreference='Stop'\n"
                      "$value=Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json\n"
                      "if ($value.CORE_BEHAVIOR -cne 'PASS') { throw 'verdict lost' }\n"
                      "if ($value.core_behavior_evidence.kind -cne 'core_behavior_evidence') { throw 'nested evidence lost' }\n"
                      "if ($value.core_behavior_evidence.runs.Count -ne 15) { throw 'runs lost' }\n"
                      "$value.acceptance_protocol\n", encoding="utf-8-sig")
    result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-File", str(script), str(path)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "professional-core-v1"


@pytest.mark.parametrize("legacy", [False, True])
def test_current_composition_cannot_use_legacy_flag_to_skip_core(tmp_path, legacy):
    binding = _binding(tmp_path)
    with pytest.raises(ValueError, match="core behavior"):
        compose_final_evidence(candidate=_candidate(binding), canary=_canary(binding), legacy_sync_bootstrap=legacy)


def test_current_composition_rejects_obsolete_case_colliding_wire_key(tmp_path):
    binding = _binding(tmp_path)
    args = core_arguments(binding, tmp_path)
    candidate = _candidate(binding)
    candidate["core_behavior"] = {"obsolete": True}
    candidate["evidence_body_sha256"] = evidence_body_sha256(candidate)
    with pytest.raises(ValueError, match="wire key collides"):
        compose_final_evidence(candidate=candidate, canary=_canary(binding, args["package_path"]), **args)


@pytest.mark.parametrize("alias", ["Core_Behavior", "CORE_BEHAVIOR_EVIDENCE", "EVIDENCE_BODY_SHA256", "nested"])
def test_composition_rejects_case_collisions_at_any_envelope_depth(tmp_path, alias):
    binding = _binding(tmp_path)
    args = core_arguments(binding, tmp_path)
    candidate = _candidate(binding)
    candidate[alias] = {"scope": 1, "Scope": 2} if alias == "nested" else {}
    candidate["evidence_body_sha256"] = evidence_body_sha256(candidate)
    with pytest.raises(ValueError, match="case-insensitive duplicate"):
        compose_final_evidence(candidate=candidate, canary=_canary(binding, args["package_path"]), **args)


@pytest.mark.parametrize("inherited", [False, True])
def test_historical_direct_and_inherited_inputs_remain_readable_not_promotable(tmp_path, inherited):
    binding = _binding(tmp_path)
    matched = _inherited_matched(binding) if inherited else _matched(binding)
    verdict = validate_historical_inputs(candidate=_candidate(binding), matched_ab=matched, canary=_canary(binding))
    assert verdict == {"HISTORICAL_INPUTS": "PASS", "release_eligible": False}
    assert "FULL_RELEASE_CODEX" not in verdict


@pytest.mark.parametrize("tamper", ["candidate", "matched", "canary", "changed_inheritance", "missing_inheritance"])
def test_historical_validation_preserves_original_checks(tmp_path, tamper):
    binding = _binding(tmp_path)
    candidate, matched, canary = _candidate(binding), _matched(binding), _canary(binding)
    if tamper == "candidate": candidate["CANDIDATE_OFFLINE"] = "NOT_PASS"
    elif tamper == "matched":
        matched["candidate_package"]["sha256"] = "9" * 64
        matched["evidence_body_sha256"] = evidence_body_sha256(matched)
    elif tamper == "canary":
        canary["release_binding"] = {**binding, "version": "9.9.9"}
        canary["evidence_body_sha256"] = evidence_body_sha256(canary)
    else:
        matched = _inherited_matched(binding)
        matched["inheritance"]["candidate_model_surface_sha256"] = "6" * 64 if tamper == "changed_inheritance" else ""
        if tamper == "missing_inheritance": matched["inheritance"]["previous_model_surface_sha256"] = ""
        matched["evidence_body_sha256"] = evidence_body_sha256(matched)
    with pytest.raises(ValueError):
        validate_historical_inputs(candidate=candidate, matched_ab=matched, canary=canary)


@pytest.mark.parametrize("tamper", ["surfaces", "benchmark", "digest"])
def test_historical_matched_benchmark_is_still_fail_closed(tmp_path, tamper):
    binding = _binding(tmp_path)
    matched = _matched(binding)
    if tamper == "surfaces": del matched["surfaces"]
    elif tamper == "benchmark": matched["benchmark"] = {"id": "invented", "mode": "DIRECT_NEW_BASELINE"}
    else: matched["surfaces"]["legacy_sha256"] = "d" * 64
    matched["evidence_body_sha256"] = evidence_body_sha256(matched)
    with pytest.raises(ValueError):
        _validate_matched(matched, binding)


def test_current_composition_requires_package_bound_canary(tmp_path):
    binding = _binding(tmp_path)
    with pytest.raises(ValueError, match="canary"):
        compose_final_evidence(candidate=_candidate(binding), canary=_canary(binding), **core_arguments(binding, tmp_path))


@pytest.mark.parametrize("tamper", ["missing_before", "missing_after", "unequal", "missing_foundation", "wrong_foundation", "missing_preserved"])
def test_current_canary_does_not_trust_self_hashed_rollback_pass(tmp_path, tamper):
    binding = _binding(tmp_path)
    args = core_arguments(binding, tmp_path)
    canary = _canary(binding, args["package_path"])
    if tamper == "missing_before": del canary["rollback"]["before_surface_sha256"]
    elif tamper == "missing_after": del canary["rollback"]["after_surface_sha256"]
    elif tamper == "unequal": canary["rollback"]["after_surface_sha256"] = "9" * 64
    elif tamper == "missing_foundation": del canary["foundation_sha256"]
    elif tamper == "wrong_foundation": canary["foundation_sha256"] = "9" * 64
    else: del canary["preserved_files"]
    canary["evidence_body_sha256"] = evidence_body_sha256(canary)
    with pytest.raises(ValueError, match="canary"):
        compose_final_evidence(candidate=_candidate(binding), canary=canary, **args)
