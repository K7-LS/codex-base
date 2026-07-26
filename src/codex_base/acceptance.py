from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .catalog import load_catalog
from .token_audit import audit_static_context


_SKIPPED_PARTS = {".git", "__pycache__", ".pytest_cache", "dist", ".work"}
_TEXT_SUFFIXES = {
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
    ".tmpl",
    ".lsp",
}
_SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


def _repository_files(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and not any(part in _SKIPPED_PARTS for part in path.parts)
            and path.suffix.lower() not in {".pyc", ".pyo"}
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _read_text(path: Path) -> str | None:
    if path.suffix.lower() not in _TEXT_SUFFIXES:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def validate_structured_files(repo_root: Path) -> dict[str, object]:
    counts = {"json": 0, "toml": 0, "yaml": 0}
    errors: list[dict[str, str]] = []
    for path in _repository_files(repo_root):
        relative = path.relative_to(repo_root).as_posix()
        try:
            if path.suffix.lower() == ".json":
                json.loads(path.read_text(encoding="utf-8"))
                counts["json"] += 1
            elif path.suffix.lower() == ".toml":
                tomllib.loads(path.read_text(encoding="utf-8"))
                counts["toml"] += 1
            elif path.suffix.lower() in {".yaml", ".yml"}:
                yaml.safe_load(path.read_text(encoding="utf-8"))
                counts["yaml"] += 1
        except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
            errors.append({"path": relative, "error": str(exc)})
    return {
        "status": "PASS" if not errors else "NOT_PASS",
        "counts": counts,
        "errors": errors,
    }


def scan_secrets(repo_root: Path) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    for path in _repository_files(repo_root):
        text = _read_text(path)
        if text is None:
            continue
        relative = path.relative_to(repo_root).as_posix()
        for line_number, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in _SECRET_PATTERNS.items():
                if pattern.search(line):
                    findings.append(
                        {
                            "path": relative,
                            "line": line_number,
                            "kind": kind,
                        }
                    )
    return {
        "status": "PASS" if not findings else "NOT_PASS",
        "patterns": sorted(_SECRET_PATTERNS),
        "findings": findings,
    }


def scan_automatic_network_surfaces(repo_root: Path) -> dict[str, object]:
    roots = (
        repo_root / "runtime",
        repo_root / "control-skills" / "sync-base",
    )
    files = [
        path
        for root in roots
        for path in _repository_files(root)
        if path.suffix.lower() in {".json", ".ps1", ".py"}
    ]
    payload = "\n".join(
        path.read_text(encoding="utf-8")
        for path in files
    )
    hosts = sorted(
        {
            (urlparse(value).hostname or "").lower()
            for value in re.findall(r"https?://[^\s'\"`]+", payload)
            if urlparse(value).hostname
        }
    )
    gh_operations = sorted(
        {
            match.group(1)
            for match in re.finditer(
                r"[\"']release[\"'][\s\S]{0,100}?"
                r"[\"'](download|list|verify|verify-asset)[\"']",
                payload,
            )
        }
    )
    reverse_patterns = {
        "http_write_method": re.compile(
            r"(?:Invoke-RestMethod|Invoke-WebRequest)[^\n]*"
            r"-Method\s+(?:Post|Put|Patch|Delete)\b",
            re.IGNORECASE,
        ),
        "gh_mutation": re.compile(
            r"[\"'](?:api|release|repo)[\"'][\s\S]{0,80}?"
            r"[\"'](?:create|delete|edit|upload|push)[\"']",
            re.IGNORECASE,
        ),
        "telemetry_sdk": re.compile(
            r"\b(?:sentry_sdk|opentelemetry|segment\.analytics|posthog)\b",
            re.IGNORECASE,
        ),
    }
    findings = [
        {"kind": kind, "match": match.group(0)[:160]}
        for kind, pattern in reverse_patterns.items()
        for match in pattern.finditer(payload)
    ]
    expected_hosts = ["api.github.com"]
    allowed_gh = [
        "release download",
        "release list",
        "release verify",
        "release verify-asset",
    ]
    normalized_gh = [f"release {value}" for value in gh_operations]
    passed = (
        hosts == expected_hosts
        and normalized_gh == allowed_gh
        and not findings
    )
    return {
        "status": "PASS" if passed else "NOT_PASS",
        "automatic_hosts": hosts,
        "permitted_gh_operations": normalized_gh,
        "reverse_flow_findings": findings,
        "scope": [
            path.relative_to(repo_root).as_posix()
            for path in sorted(files)
        ],
        "limitations": [
            "On-demand capability skills are outside this automatic-flow scan.",
            "The release verifier performs GitHub read/download operations only.",
        ],
    }


def _component_counts(repo_root: Path) -> dict[str, int]:
    catalog = load_catalog(repo_root)
    return {
        "agents": len(catalog["agents"]),
        "capability_skills": len(catalog["skills"]),
        "control_skills": len(
            list((repo_root / "control-skills").glob("*/SKILL.md"))
        ),
        "cold": sum(
            len(values)
            for values in json.loads(
                (repo_root / "catalog" / "cold.json").read_text(
                    encoding="utf-8"
                )
            ).values()
        ),
    }


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def write_acceptance_evidence(
    repo_root: Path,
    destination: Path,
    version: str,
    foundation_evidence: dict[str, object] | None,
    offline_integration: dict[str, object] | None = None,
    test_evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    structured = validate_structured_files(repo_root)
    secrets = scan_secrets(repo_root)
    network = scan_automatic_network_surfaces(repo_root)
    token = audit_static_context(repo_root)
    counts = _component_counts(repo_root)
    content_pass = (
        counts
        == {
            "agents": 16,
            "capability_skills": 37,
            "control_skills": 1,
            "cold": 25,
        }
        and structured["status"] == "PASS"
        and secrets["status"] == "PASS"
        and network["status"] == "PASS"
        and token["results"]["STATIC_TOKEN_ACCEPTANCE"] == "PASS"
    )
    foundation_status = (
        str(foundation_evidence.get("FOUNDATION_SYNTHETIC", "NOT_PASS"))
        if foundation_evidence
        else "NOT_RUN"
    )
    integration_status = (
        str(offline_integration.get("status", "NOT_PASS"))
        if offline_integration
        else "NOT_RUN"
    )
    tests_status = (
        str(test_evidence.get("status", "NOT_PASS"))
        if test_evidence
        else "NOT_RUN"
    )
    candidate_offline = (
        content_pass
        and foundation_status == "PASS"
        and integration_status == "PASS"
        and tests_status == "PASS"
    )
    evidence: dict[str, object] = {
        "schema_version": 1,
        "target": "codex",
        "version": version,
        "component_counts": counts,
        "checks": {
            "structured_files": structured,
            "secret_scan": secrets,
            "automatic_network": network,
        },
        "token_acceptance": token,
        "foundation": foundation_evidence,
        "offline_integration": offline_integration,
        "tests": test_evidence,
        "OFFLINE_CODEX_CONTENT": "PASS" if content_pass else "NOT_PASS",
        "STATIC_TOKEN_ACCEPTANCE": token["results"][
            "STATIC_TOKEN_ACCEPTANCE"
        ],
        "FOUNDATION_SYNTHETIC": foundation_status,
        "CODEX_OFFLINE_INTEGRATION": integration_status,
        "CODEX_TESTS": tests_status,
        "CANDIDATE_OFFLINE": "PASS" if candidate_offline else "NOT_PASS",
        "MATCHED_AB": "NOT_RUN",
        "CODEX_CANARY": "NOT_RUN",
        "FULL_RELEASE_CODEX": "NOT_PASS",
        "PROGRAM_RELEASE": "0/3",
        "release_permissions": {
            "paid_matched_ab": "BLOCKED_OWNER_APPROVAL",
            "hub_canary": "BLOCKED_OWNER_APPROVAL",
            "stable_release": "BLOCKED",
        },
        "limitations": [
            "Static token estimates are not provider billing measurements.",
            "FULL_RELEASE_CODEX cannot pass without matched A/B and hub canary.",
            "A stable release must reuse the accepted candidate ZIP bytes.",
        ],
    }
    payload = _json_bytes(evidence)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    evidence["evidence_sha256"] = hashlib.sha256(payload).hexdigest()
    # The hash describes the canonical evidence body before its self-reference.
    destination.write_bytes(_json_bytes(evidence))
    return evidence
