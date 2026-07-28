from __future__ import annotations

import hashlib
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .acceptance import evidence_body_sha256


SUPPORTED_CLIENT = "0.146.0-alpha.3.1"
MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "low"
MAX_INPUT_TOKENS = 100_000
MIN_MEDIAN_INPUT_REDUCTION = 0.25
DISABLED_TOOL_FEATURES = (
    "apps",
    "auth_elicitation",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "code_mode_host",
    "computer_use",
    "goals",
    "guardian_approval",
    "hooks",
    "image_generation",
    "in_app_browser",
    "memories",
    "multi_agent",
    "plugin_sharing",
    "plugins",
    "remote_compaction_v2",
    "remote_plugin",
    "shell_snapshot",
    "shell_tool",
    "skill_mcp_dependency_install",
    "skill_search",
    "tool_call_mcp_elicitation",
    "tool_suggest",
    "workspace_dependencies",
)
FAIL_CLOSED_CONFIG_OVERRIDES = (
    f'model_reasoning_effort="{REASONING_EFFORT}"',
    'approval_policy="never"',
    'web_search="disabled"',
    "analytics.enabled=false",
    "feedback.enabled=false",
    'otel.exporter="none"',
    'otel.trace_exporter="none"',
    'otel.metrics_exporter="none"',
    "otel.log_user_prompt=false",
)
SAFE_ITEM_EVENT_TYPES = {
    "item.started",
    "item.updated",
    "item.completed",
}
SAFE_ITEM_TYPE_CATEGORIES = {
    "agent_message": "message",
    "reasoning": "reasoning",
    "command_execution": "tool",
    "file_change": "tool",
    "mcp_tool_call": "tool",
    "dynamic_tool_call": "tool",
    "web_search": "tool",
    "image_view": "tool",
    "image_generation": "tool",
    "collab_tool_call": "tool",
    "collab_agent_tool_call": "tool",
    "sleep": "tool",
    "todo_list": "workflow",
    "plan": "workflow",
    "sub_agent_activity": "workflow",
    "entered_review_mode": "workflow",
    "exited_review_mode": "workflow",
    "context_compaction": "workflow",
    "user_message": "protocol",
    "hook_prompt": "protocol",
}


def _privacy_safe_item_event(
    event_type: Any,
    item_type: Any,
) -> dict[str, str]:
    if (
        not isinstance(event_type, str)
        or event_type not in SAFE_ITEM_EVENT_TYPES
    ):
        return {
            "event_type": "item.unknown",
            "item_type": "unrecognized",
            "category": "unknown",
        }
    category = (
        SAFE_ITEM_TYPE_CATEGORIES.get(item_type)
        if isinstance(item_type, str)
        else None
    )
    if category is None:
        return {
            "event_type": event_type,
            "item_type": "unrecognized",
            "category": "unknown",
        }
    return {
        "event_type": event_type,
        "item_type": item_type,
        "category": category,
    }


def _failure_code_for_item_category(category: str) -> str:
    return {
        "tool": "tool_event",
        "workflow": "workflow_event",
        "protocol": "protocol_item_event",
    }.get(category, "unexpected_item_event")


class GuardViolation(RuntimeError):
    """Raised when a paid run crosses a pre-authorized safety boundary."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "guard_violation",
        safe_details: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_details = safe_details


@dataclass(frozen=True)
class RunSpec:
    variant: str
    prompt_id: str
    prompt: str


def planned_runs() -> tuple[RunSpec, ...]:
    """Return the immutable, owner-approved four-call matrix."""

    return (
        RunSpec("legacy", "hello", "привет"),
        RunSpec("candidate", "hello", "привет"),
        RunSpec("legacy", "capabilities", "что ты умеешь"),
        RunSpec("candidate", "capabilities", "что ты умеешь"),
    )


def build_codex_command(
    *,
    codex: str,
    workspace: Path,
    prompt: str,
) -> list[str]:
    """Build a no-tools, low-effort, ephemeral Codex invocation."""

    command = [
        codex,
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--skip-git-repo-check",
        "-s",
        "read-only",
        "-C",
        str(workspace.resolve()),
        "-m",
        MODEL,
    ]
    for override in FAIL_CLOSED_CONFIG_OVERRIDES:
        command.extend(["-c", override])
    for feature in DISABLED_TOOL_FEATURES:
        command.extend(["--disable", feature])
    command.append(prompt)
    return command


def build_feature_preflight_command(*, codex: str) -> list[str]:
    """Build a zero-model command that validates every A/B control."""

    command = [codex, "features", "list"]
    for override in FAIL_CLOSED_CONFIG_OVERRIDES:
        command.extend(["-c", override])
    for feature in DISABLED_TOOL_FEATURES:
        command.extend(["--disable", feature])
    return command


def parse_feature_states(output: str) -> dict[str, bool]:
    """Require every protected Codex feature to exist and be disabled."""

    parsed: dict[str, bool] = {}
    for raw_line in output.splitlines():
        fields = raw_line.split()
        if len(fields) < 3 or fields[-1] not in {"true", "false"}:
            raise GuardViolation(
                "invalid feature-list output",
                code="feature_preflight",
            )
        parsed[fields[0]] = fields[-1] == "true"
    if not parsed:
        raise GuardViolation(
            "invalid feature-list output",
            code="feature_preflight",
        )
    unsafe = [
        feature
        for feature in DISABLED_TOOL_FEATURES
        if feature not in parsed or parsed[feature]
    ]
    if unsafe:
        raise GuardViolation(
            "protected features are missing or still enabled: "
            + ", ".join(unsafe),
            code="feature_preflight",
        )
    return {feature: parsed[feature] for feature in DISABLED_TOOL_FEATURES}


def _validated_usage(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise GuardViolation("turn.completed usage is missing")
    required = (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    )
    usage: dict[str, int] = {}
    for name in required:
        token_count = value.get(name)
        if (
            not isinstance(token_count, int)
            or isinstance(token_count, bool)
            or token_count < 0
        ):
            raise GuardViolation(f"turn.completed usage is invalid: {name}")
        usage[name] = token_count
    if usage["input_tokens"] > MAX_INPUT_TOKENS:
        raise GuardViolation(
            "input token guard exceeded 100000; stop before another call",
            code="input_token_guard",
        )
    return usage


def inspect_event(event: Any) -> dict[str, Any]:
    """Validate one Codex JSONL event and return evidence-safe observations."""

    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
        raise GuardViolation("Codex emitted an invalid JSONL event")
    event_type = event["type"]
    if event_type in {"error", "turn.failed"}:
        raise GuardViolation(f"Codex run failed: {event_type}")
    if event_type == "turn.completed":
        return {"usage": _validated_usage(event.get("usage"))}
    if event_type in {"thread.started", "turn.started"}:
        return {}
    if event_type.startswith("item."):
        item = event.get("item")
        if not isinstance(item, dict):
            raise GuardViolation("Codex item event has no item object")
        item_type = item.get("type")
        if (
            event_type not in SAFE_ITEM_EVENT_TYPES
            or not isinstance(item_type, str)
            or item_type not in {"agent_message", "reasoning"}
        ):
            safe_details = _privacy_safe_item_event(
                event_type,
                item_type,
            )
            failure_code = _failure_code_for_item_category(
                safe_details["category"]
            )
            raise GuardViolation(
                "unexpected item event detected; stop the paid matrix",
                code=failure_code,
                safe_details=safe_details,
            )
        if (
            event_type == "item.completed"
            and item_type == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            return {"message": item["text"]}
        return {}
    raise GuardViolation(f"unexpected Codex JSONL event: {event_type}")


def _median(values: Iterable[int]) -> float:
    materialized = list(values)
    if not materialized:
        raise ValueError("matched A/B result set is empty")
    return float(statistics.median(materialized))


def summarize_results(
    results: list[dict[str, Any]],
    *,
    client_version: str,
    legacy_surface_sha256: str,
    candidate_surface_sha256: str,
    candidate_package_sha256: str,
    candidate_package_bytes: int,
) -> dict[str, Any]:
    """Create PII-free evidence for the fixed four-call matrix."""

    expected = [(run.variant, run.prompt_id) for run in planned_runs()]
    actual = [
        (str(result.get("variant")), str(result.get("prompt_id")))
        for result in results
    ]
    if actual != expected:
        raise ValueError("matched A/B results do not match the approved matrix")
    if client_version != SUPPORTED_CLIENT:
        raise ValueError("matched A/B client version is unsupported")
    for digest in (
        legacy_surface_sha256,
        candidate_surface_sha256,
        candidate_package_sha256,
    ):
        if (
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("matched A/B surface digest is invalid")
    if (
        not isinstance(candidate_package_bytes, int)
        or isinstance(candidate_package_bytes, bool)
        or candidate_package_bytes <= 0
    ):
        raise ValueError("matched A/B candidate package size is invalid")

    safe_runs: list[dict[str, Any]] = []
    for result in results:
        usage = _validated_usage(result.get("usage"))
        digest = str(result.get("result_sha256") or "")
        if (
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("matched A/B result digest is invalid")
        safe_runs.append(
            {
                "variant": str(result["variant"]),
                "prompt_id": str(result["prompt_id"]),
                "usage": usage,
                "result_sha256": digest,
                "tool_events": 0,
            }
        )

    legacy_median = _median(
        run["usage"]["input_tokens"]
        for run in safe_runs
        if run["variant"] == "legacy"
    )
    candidate_median = _median(
        run["usage"]["input_tokens"]
        for run in safe_runs
        if run["variant"] == "candidate"
    )
    reduction = (
        0.0
        if legacy_median == 0
        else 1.0 - (candidate_median / legacy_median)
    )
    passed = reduction >= MIN_MEDIAN_INPUT_REDUCTION
    evidence = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "MATCHED_AB": "PASS" if passed else "NOT_PASS",
        "calls_authorized": 4,
        "calls_completed": len(safe_runs),
        "client": {
            "id": "codex-cli",
            "version": client_version,
        },
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "workspace": "empty-isolated",
        "tools": {
            "disabled_features": list(DISABLED_TOOL_FEATURES),
            "web_search": "disabled",
            "unexpected_tool_events": 0,
        },
        "telemetry": {
            "analytics": False,
            "feedback": False,
            "otel_exporter": "none",
            "otel_trace_exporter": "none",
            "otel_metrics_exporter": "none",
            "prompt_logging": False,
        },
        "surfaces": {
            "legacy_sha256": legacy_surface_sha256,
            "candidate_sha256": candidate_surface_sha256,
        },
        "candidate_package": {
            "sha256": candidate_package_sha256,
            "bytes": candidate_package_bytes,
        },
        "thresholds": {
            "max_input_tokens_per_call": MAX_INPUT_TOKENS,
            "median_input_reduction_min": MIN_MEDIAN_INPUT_REDUCTION,
        },
        "metrics": {
            "legacy_median_input_tokens": legacy_median,
            "candidate_median_input_tokens": candidate_median,
            "median_input_reduction": reduction,
        },
        "runs": safe_runs,
        "privacy": {
            "prompt_text_included": False,
            "response_text_included": False,
            "credentials_included": False,
            "personal_data_included": False,
        },
    }
    evidence["evidence_body_sha256"] = evidence_body_sha256(evidence)
    return evidence


def summarize_abort(
    *,
    client_version: str,
    failure_code: str,
    calls_started: int,
    completed_results: list[dict[str, Any]],
    legacy_surface_sha256: str,
    candidate_surface_sha256: str,
    candidate_package_sha256: str,
    candidate_package_bytes: int,
    stop_event: Any = None,
) -> dict[str, Any]:
    """Create a PII-free terminal report after a guarded paid-matrix stop."""

    privacy_safe_stop_event = (
        _privacy_safe_item_event(
            stop_event.get("event_type"),
            stop_event.get("item_type"),
        )
        if isinstance(stop_event, dict)
        else None
    )
    if privacy_safe_stop_event is not None:
        failure_code = _failure_code_for_item_category(
            privacy_safe_stop_event["category"]
        )
    allowed_failure_codes = {
        "call_failed",
        "feature_preflight",
        "guard_violation",
        "input_token_guard",
        "invalid_event",
        "protocol_item_event",
        "timeout",
        "tool_event",
        "unexpected_item_event",
        "workflow_event",
    }
    if failure_code not in allowed_failure_codes:
        failure_code = "guard_violation"
    if (
        not isinstance(calls_started, int)
        or isinstance(calls_started, bool)
        or not 0 <= calls_started <= len(planned_runs())
        or len(completed_results) > calls_started
    ):
        raise ValueError("matched A/B abort call counts are invalid")

    safe_completed: list[dict[str, Any]] = []
    expected = [(run.variant, run.prompt_id) for run in planned_runs()]
    actual = [
        (str(result.get("variant")), str(result.get("prompt_id")))
        for result in completed_results
    ]
    if actual != expected[: len(actual)]:
        raise ValueError("matched A/B abort results do not match the matrix")
    for result in completed_results:
        usage = _validated_usage(result.get("usage"))
        result_digest = str(result.get("result_sha256") or "")
        if (
            len(result_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in result_digest
            )
        ):
            raise ValueError("matched A/B abort result digest is invalid")
        safe_completed.append(
            {
                "variant": str(result["variant"]),
                "prompt_id": str(result["prompt_id"]),
                "usage": usage,
                "result_sha256": result_digest,
                "tool_events": 0,
            }
        )

    evidence = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "MATCHED_AB": "NOT_PASS",
        "calls_authorized": 4,
        "calls_started": calls_started,
        "calls_completed": len(safe_completed),
        "repeat_authorized": False,
        "stop_reason": failure_code,
        "client": {
            "id": "codex-cli",
            "version": client_version,
        },
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "workspace": "empty-isolated",
        "tools": {
            "disabled_features": list(DISABLED_TOOL_FEATURES),
            "web_search": "disabled",
        },
        "surfaces": {
            "legacy_sha256": legacy_surface_sha256,
            "candidate_sha256": candidate_surface_sha256,
        },
        "candidate_package": {
            "sha256": candidate_package_sha256,
            "bytes": candidate_package_bytes,
        },
        "runs_completed": safe_completed,
        "privacy": {
            "prompt_text_included": False,
            "response_text_included": False,
            "credentials_included": False,
            "personal_data_included": False,
            "error_text_included": False,
        },
    }
    if privacy_safe_stop_event is not None:
        evidence["stop_event"] = privacy_safe_stop_event
    evidence["evidence_body_sha256"] = evidence_body_sha256(evidence)
    return evidence


def response_sha256(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()
