from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .acceptance import (
    evidence_body_sha256,
    release_binding_from_manifest,
)


REQUIRED_FULL_RELEASE_GATES = (
    "FOUNDATION_SYNTHETIC",
    "OFFLINE_CODEX_CONTENT",
    "STATIC_TOKEN_ACCEPTANCE",
    "CODEX_OFFLINE_INTEGRATION",
    "CODEX_TESTS",
    "CANDIDATE_OFFLINE",
    "MATCHED_AB",
    "CODEX_CANARY",
    "FULL_RELEASE_CODEX",
)


@dataclass(frozen=True)
class PromotionResult:
    zip_path: Path
    manifest_path: Path
    component_lock_path: Path
    evidence_path: Path
    zip_sha256: str


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _verify_evidence(
    evidence: dict[str, object],
    binding: dict[str, object],
    *,
    require_full_release: bool,
) -> None:
    if evidence.get("evidence_body_sha256") != evidence_body_sha256(
        evidence
    ):
        raise ValueError("acceptance evidence body hash differs")
    if evidence.get("release_binding") != binding:
        raise ValueError("acceptance evidence release binding differs")
    if require_full_release:
        for gate in REQUIRED_FULL_RELEASE_GATES:
            if evidence.get(gate) != "PASS":
                raise ValueError(f"{gate} is not PASS")
        if evidence.get("PROGRAM_RELEASE") != "1/3":
            raise ValueError("PROGRAM_RELEASE is not 1/3")


def _verify_candidate(
    candidate_dir: Path,
) -> tuple[
    dict[str, object],
    dict[str, object],
    Path,
    bytes,
    bytes,
]:
    manifest_path = candidate_dir / "release-manifest.json"
    lock_path = candidate_dir / "components.lock.json"
    offline_evidence_path = candidate_dir / "acceptance-evidence.json"
    manifest = _load_json(manifest_path)
    version = str(manifest.get("version") or "")
    if (
        manifest.get("channel") != "candidate"
        or manifest.get("target") != "codex"
        or manifest.get("tag") != f"codex-v{version}"
    ):
        raise ValueError("source release manifest is not candidate")
    binding = release_binding_from_manifest(manifest)

    lock_bytes = lock_path.read_bytes()
    if _sha256_bytes(lock_bytes) != manifest.get(
        "components_lock_sha256"
    ):
        raise ValueError("candidate components lock hash differs")
    offline_evidence_bytes = offline_evidence_path.read_bytes()
    if _sha256_bytes(offline_evidence_bytes) != manifest.get(
        "acceptance_evidence_sha256"
    ):
        raise ValueError("candidate evidence hash differs")
    offline_evidence = json.loads(offline_evidence_bytes)
    if not isinstance(offline_evidence, dict):
        raise ValueError("candidate evidence must contain an object")
    _verify_evidence(
        offline_evidence,
        binding,
        require_full_release=False,
    )
    if offline_evidence.get("CANDIDATE_OFFLINE") != "PASS":
        raise ValueError("candidate offline acceptance is not PASS")

    asset = manifest.get("asset")
    if not isinstance(asset, dict):
        raise ValueError("candidate asset record is invalid")
    zip_path = candidate_dir / str(asset.get("name") or "")
    zip_bytes = zip_path.read_bytes()
    if (
        _sha256_bytes(zip_bytes) != asset.get("sha256")
        or len(zip_bytes) != asset.get("bytes")
        or zip_path.name != f"codex-base-{version}.zip"
    ):
        raise ValueError("candidate ZIP hash differs")
    with zipfile.ZipFile(zip_path) as archive:
        package_manifest_bytes = archive.read("package-manifest.json")
        embedded_lock = archive.read(
            ".codex/base/components.lock.json"
        )
    if _sha256_bytes(package_manifest_bytes) != manifest.get(
        "package_manifest_sha256"
    ):
        raise ValueError("candidate package manifest hash differs")
    package_manifest = json.loads(package_manifest_bytes)
    if (
        package_manifest.get("target") != "codex"
        or package_manifest.get("version") != version
    ):
        raise ValueError("candidate package target/version differs")
    if embedded_lock != lock_bytes:
        raise ValueError("candidate embedded components lock differs")
    return manifest, binding, zip_path, zip_bytes, lock_bytes


def promote_candidate(
    candidate_dir: Path,
    final_evidence_path: Path,
    output_dir: Path,
) -> PromotionResult:
    (
        candidate_manifest,
        binding,
        source_zip,
        zip_bytes,
        lock_bytes,
    ) = _verify_candidate(candidate_dir)
    final_evidence_bytes = final_evidence_path.read_bytes()
    final_evidence = json.loads(final_evidence_bytes)
    if not isinstance(final_evidence, dict):
        raise ValueError("final evidence must contain an object")
    _verify_evidence(
        final_evidence,
        binding,
        require_full_release=True,
    )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("stable output directory must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)

    destination_zip = output_dir / source_zip.name
    destination_zip.write_bytes(zip_bytes)
    destination_lock = output_dir / "components.lock.json"
    destination_lock.write_bytes(lock_bytes)
    destination_evidence = output_dir / "acceptance-evidence.json"
    destination_evidence.write_bytes(final_evidence_bytes)

    stable_manifest = dict(candidate_manifest)
    stable_manifest["channel"] = "stable"
    stable_manifest["acceptance_evidence_sha256"] = _sha256_bytes(
        final_evidence_bytes
    )
    stable_manifest["promoted_from_candidate_manifest_sha256"] = (
        _sha256_bytes(
            (candidate_dir / "release-manifest.json").read_bytes()
        )
    )
    destination_manifest = output_dir / "release-manifest.json"
    destination_manifest.write_bytes(_json_bytes(stable_manifest))

    if destination_zip.read_bytes() != zip_bytes:
        raise AssertionError("promotion rebuilt or changed candidate ZIP bytes")
    return PromotionResult(
        zip_path=destination_zip,
        manifest_path=destination_manifest,
        component_lock_path=destination_lock,
        evidence_path=destination_evidence,
        zip_sha256=_sha256_bytes(zip_bytes),
    )
