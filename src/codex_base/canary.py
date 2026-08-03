from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .acceptance import evidence_body_sha256


EXPECTED_PHASES = {
    "plan": "READY",
    "install": "INSTALLED",
    "doctor": "HEALTHY",
    "inventory": "INVENTORIED",
    "rollback": "ROLLED_BACK",
}


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def surface_digest(home: Path) -> str:
    """Hash the isolated user surface, excluding Foundation's own journal."""

    digest = hashlib.sha256()
    files = sorted(
        (
            path
            for path in home.rglob("*")
            if path.is_file()
            and ".llm-foundation" not in path.relative_to(home).parts
        ),
        key=lambda path: path.relative_to(home).as_posix(),
    )
    for path in files:
        relative = path.relative_to(home).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\n")
    return digest.hexdigest()


def build_canary_evidence(
    *,
    release_binding: dict[str, Any],
    client_version: str,
    foundation_sha256: str,
    before_surface_sha256: str,
    after_rollback_surface_sha256: str,
    phase_statuses: dict[str, str],
    discovery: dict[str, int],
    preserved_files: int,
) -> dict[str, Any]:
    asset = release_binding.get("asset")
    valid = (
        release_binding.get("target") == "codex"
        and isinstance(release_binding.get("version"), str)
        and isinstance(asset, dict)
        and _valid_sha256(asset.get("sha256"))
        and isinstance(asset.get("bytes"), int)
        and not isinstance(asset.get("bytes"), bool)
        and asset["bytes"] > 0
        and client_version == "0.146.0-alpha.3.1"
        and _valid_sha256(foundation_sha256)
        and _valid_sha256(before_surface_sha256)
        and before_surface_sha256 == after_rollback_surface_sha256
        and phase_statuses == EXPECTED_PHASES
        and discovery == {"agents": 16, "skills": 39}
        and isinstance(preserved_files, int)
        and not isinstance(preserved_files, bool)
        and preserved_files >= 7
    )
    if not valid:
        raise ValueError("Codex canary did not satisfy the release contract")
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "target": "codex",
        "version": release_binding["version"],
        "generated_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "release_binding": release_binding,
        "client": {
            "id": "codex-cli",
            "version": client_version,
        },
        "foundation_sha256": foundation_sha256,
        "phases": dict(phase_statuses),
        "discovery": dict(discovery),
        "rollback": {
            "before_surface_sha256": before_surface_sha256,
            "after_surface_sha256": after_rollback_surface_sha256,
            "byte_identical": True,
        },
        "preserved_files": preserved_files,
        "network": "offline-local-files-only",
        "model_requests": 0,
        "credentials_included": False,
        "personal_data_included": False,
        "CODEX_CANARY": "PASS",
    }
    evidence["evidence_body_sha256"] = evidence_body_sha256(evidence)
    return evidence
