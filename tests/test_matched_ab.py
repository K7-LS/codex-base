from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from codex_base.matched_ab import (
    DISABLED_TOOL_FEATURES,
    GuardViolation,
    build_codex_command,
    build_feature_preflight_command,
    inspect_event,
    parse_feature_states,
    planned_runs,
    summarize_abort,
    summarize_results,
)
from codex_base.acceptance import evidence_body_sha256


def test_matched_ab_plan_is_exactly_four_balanced_calls():
    runs = planned_runs()

    assert [
        (run.variant, run.prompt_id, run.prompt)
        for run in runs
    ] == [
        ("legacy", "hello", "привет"),
        ("candidate", "hello", "привет"),
        ("legacy", "capabilities", "что ты умеешь"),
        ("candidate", "capabilities", "что ты умеешь"),
    ]


def test_codex_command_pins_model_effort_and_disables_tools(tmp_path):
    command = build_codex_command(
        codex="codex",
        workspace=tmp_path / "empty",
        prompt="привет",
    )

    assert command[:2] == ["codex", "exec"]
    assert "--json" in command
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "--strict-config" in command
    assert ["-m", "gpt-5.6-terra"] == command[
        command.index("-m") : command.index("-m") + 2
    ]
    assert 'model_reasoning_effort="low"' in command
    assert 'approval_policy="never"' in command
    assert 'web_search="disabled"' in command
    assert "analytics.enabled=false" in command
    assert "feedback.enabled=false" in command
    assert 'otel.exporter="none"' in command
    assert 'otel.trace_exporter="none"' in command
    assert 'otel.metrics_exporter="none"' in command
    assert command.count("--disable") == len(DISABLED_TOOL_FEATURES)
    for feature in DISABLED_TOOL_FEATURES:
        assert feature in command
    assert "--search" not in command
    assert command[-1] == "привет"


def test_feature_preflight_reuses_all_fail_closed_controls():
    command = build_feature_preflight_command(codex="codex")

    assert command[:3] == ["codex", "features", "list"]
    assert 'model_reasoning_effort="low"' in command
    assert 'approval_policy="never"' in command
    assert 'web_search="disabled"' in command
    assert "analytics.enabled=false" in command
    assert "feedback.enabled=false" in command
    assert 'otel.exporter="none"' in command
    assert 'otel.trace_exporter="none"' in command
    assert 'otel.metrics_exporter="none"' in command
    assert "otel.log_user_prompt=false" in command
    assert command.count("--disable") == len(DISABLED_TOOL_FEATURES)


def test_feature_preflight_parser_requires_every_control_to_be_false():
    output = "\n".join(
        f"{feature:<38} stable             false"
        for feature in DISABLED_TOOL_FEATURES
    )

    states = parse_feature_states(output)

    assert states == {feature: False for feature in DISABLED_TOOL_FEATURES}


@pytest.mark.parametrize(
    "feature",
    [
        "auth_elicitation",
        "goals",
        "guardian_approval",
        "memories",
        "plugin_sharing",
        "remote_compaction_v2",
        "tool_call_mcp_elicitation",
    ],
)
def test_feature_preflight_rejects_enabled_hidden_state_or_elicitation(
    feature,
):
    output = "\n".join(
        f"{protected:<38} stable             "
        + ("true" if protected == feature else "false")
        for protected in DISABLED_TOOL_FEATURES
    )

    with pytest.raises(
        GuardViolation,
        match="missing or still enabled",
    ):
        parse_feature_states(output)


@pytest.mark.parametrize(
    "output, message",
    [
        ("apps stable true\n", "missing or still enabled"),
        ("apps stable maybe\n", "invalid feature-list"),
        ("", "invalid feature-list"),
    ],
)
def test_feature_preflight_parser_fails_closed(output, message):
    with pytest.raises(GuardViolation, match=message):
        parse_feature_states(output)


def test_event_guard_allows_messages_and_extracts_usage():
    assert inspect_event(
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "Здравствуйте!"},
        }
    ) == {"message": "Здравствуйте!"}
    assert inspect_event(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 24763,
                "cached_input_tokens": 24448,
                "output_tokens": 122,
                "reasoning_output_tokens": 0,
            },
        }
    ) == {
        "usage": {
            "input_tokens": 24763,
            "cached_input_tokens": 24448,
            "output_tokens": 122,
            "reasoning_output_tokens": 0,
        }
    }


@pytest.mark.parametrize(
    "item_type",
    [
        "command_execution",
        "file_change",
        "mcp_tool_call",
        "web_search",
        "todo_list",
        "collab_tool_call",
    ],
)
def test_event_guard_rejects_any_non_message_non_reasoning_item(item_type):
    with pytest.raises(GuardViolation, match="tool or workflow event"):
        inspect_event(
            {
                "type": "item.started",
                "item": {"type": item_type},
            }
        )


def test_event_guard_rejects_more_than_100000_input_tokens():
    with pytest.raises(GuardViolation, match="100000"):
        inspect_event(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100001,
                    "cached_input_tokens": 0,
                    "output_tokens": 1,
                    "reasoning_output_tokens": 0,
                },
            }
        )


def test_summary_uses_medians_and_never_contains_prompt_text():
    def usage(input_tokens: int) -> dict[str, int]:
        return {
            "input_tokens": input_tokens,
            "cached_input_tokens": 0,
            "output_tokens": 10,
            "reasoning_output_tokens": 0,
        }

    results = [
        {
            "variant": "legacy",
            "prompt_id": "hello",
            "usage": usage(80000),
            "result_sha256": hashlib.sha256(b"legacy-hello").hexdigest(),
        },
        {
            "variant": "candidate",
            "prompt_id": "hello",
            "usage": usage(30000),
            "result_sha256": hashlib.sha256(b"candidate-hello").hexdigest(),
        },
        {
            "variant": "legacy",
            "prompt_id": "capabilities",
            "usage": usage(100000),
            "result_sha256": hashlib.sha256(
                b"legacy-capabilities"
            ).hexdigest(),
        },
        {
            "variant": "candidate",
            "prompt_id": "capabilities",
            "usage": usage(40000),
            "result_sha256": hashlib.sha256(
                b"candidate-capabilities"
            ).hexdigest(),
        },
    ]

    evidence = summarize_results(
        results,
        client_version="0.146.0-alpha.3.1",
        legacy_surface_sha256="a" * 64,
        candidate_surface_sha256="b" * 64,
        candidate_package_sha256="c" * 64,
        candidate_package_bytes=123,
    )

    assert evidence["MATCHED_AB"] == "PASS"
    assert evidence["calls_completed"] == 4
    assert evidence["metrics"]["legacy_median_input_tokens"] == 90000
    assert evidence["metrics"]["candidate_median_input_tokens"] == 35000
    assert evidence["metrics"]["median_input_reduction"] == pytest.approx(
        1 - (35000 / 90000)
    )
    serialized = str(evidence)
    assert "привет" not in serialized
    assert "что ты умеешь" not in serialized
    assert all("result_sha256" in result for result in evidence["runs"])
    assert evidence["candidate_package"] == {
        "sha256": "c" * 64,
        "bytes": 123,
    }
    assert evidence["tools"]["disabled_features"] == list(
        DISABLED_TOOL_FEATURES
    )
    assert (
        evidence["evidence_body_sha256"]
        == evidence_body_sha256(evidence)
    )


def test_abort_evidence_is_pii_free_and_binds_the_started_matrix():
    evidence = summarize_abort(
        client_version="0.146.0-alpha.3.1",
        failure_code="tool_event",
        calls_started=2,
        completed_results=[
            {
                "variant": "legacy",
                "prompt_id": "hello",
                "usage": {
                    "input_tokens": 1200,
                    "cached_input_tokens": 1000,
                    "output_tokens": 12,
                    "reasoning_output_tokens": 0,
                },
                "result_sha256": "d" * 64,
            }
        ],
        legacy_surface_sha256="a" * 64,
        candidate_surface_sha256="b" * 64,
        candidate_package_sha256="c" * 64,
        candidate_package_bytes=123,
    )

    assert evidence["MATCHED_AB"] == "NOT_PASS"
    assert evidence["calls_authorized"] == 4
    assert evidence["calls_started"] == 2
    assert evidence["calls_completed"] == 1
    assert evidence["stop_reason"] == "tool_event"
    assert evidence["repeat_authorized"] is False
    serialized = json.dumps(evidence, ensure_ascii=False)
    assert "привет" not in serialized
    assert "что ты умеешь" not in serialized
    assert evidence["evidence_body_sha256"] == evidence_body_sha256(evidence)


def test_cli_defaults_to_dry_run_and_exposes_only_prompt_hashes(
    repo_root: Path,
):
    result = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "run_matched_ab.py")],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["would_execute"] is False
    assert plan["calls_total"] == 4
    assert len(plan["calls"]) == 4
    assert all("prompt_sha256" in call for call in plan["calls"])
    assert "привет" not in result.stdout
    assert "что ты умеешь" not in result.stdout
