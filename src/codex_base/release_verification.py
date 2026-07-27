from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .acceptance import evidence_body_sha256


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _output_digest(payload: bytes, label: str) -> str:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} did not return JSON") from error
    if not isinstance(value, (dict, list)):
        raise ValueError(f"{label} returned an invalid JSON value")
    return hashlib.sha256(payload).hexdigest()


def build_release_verification(
    *,
    manifest_path: Path,
    asset_path: Path,
    release_api: dict[str, Any],
    release_attestation_output: bytes,
    asset_attestation_output: bytes,
    gh_version: str,
) -> dict[str, Any]:
    """Build minimal post-publication evidence from successful GitHub checks."""

    manifest = _load_object(manifest_path)
    source = manifest.get("source")
    asset = manifest.get("asset")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("target") != "codex"
        or manifest.get("channel") != "stable"
        or not isinstance(source, dict)
        or not isinstance(asset, dict)
    ):
        raise ValueError("stable release manifest is invalid")
    repository = str(source.get("repository") or "").removeprefix(
        "https://github.com/"
    ).rstrip("/")
    if repository != "daniileliseev1337/codex-base":
        raise ValueError("stable release repository differs")
    if (
        release_api.get("tag_name") != manifest.get("tag")
        or release_api.get("draft") is not False
        or release_api.get("prerelease") is not False
        or release_api.get("immutable") is not True
    ):
        raise ValueError("GitHub release state is not immutable stable")
    if asset_path.name != asset.get("name") or not asset_path.is_file():
        raise ValueError("local release asset binding differs")
    payload = asset_path.read_bytes()
    if (
        hashlib.sha256(payload).hexdigest() != asset.get("sha256")
        or len(payload) != asset.get("bytes")
    ):
        raise ValueError("local release asset binding differs")
    if not gh_version.startswith("gh version "):
        raise ValueError("GitHub CLI version evidence is invalid")
    release_output_sha256 = _output_digest(
        release_attestation_output,
        "gh release verify",
    )
    asset_output_sha256 = _output_digest(
        asset_attestation_output,
        "gh release verify-asset",
    )
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "repository": repository,
        "tag": manifest["tag"],
        "release_state": {
            "draft": False,
            "prerelease": False,
            "immutable": True,
        },
        "release_attestation": "PASS",
        "assets": [
            {
                "name": asset["name"],
                "sha256": asset["sha256"],
                "bytes": asset["bytes"],
                "attestation": "PASS",
            }
        ],
        "verification_commands": {
            "gh_version": gh_version.splitlines()[0],
            "release_output_sha256": release_output_sha256,
            "asset_output_sha256": asset_output_sha256,
        },
        "privacy": {
            "raw_attestation_output_included": False,
            "credentials_included": False,
            "personal_data_included": False,
        },
        "RELEASE_INTEGRITY": "PASS",
    }
    evidence["evidence_body_sha256"] = evidence_body_sha256(evidence)
    return evidence
