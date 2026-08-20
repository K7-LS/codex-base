from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from codex_base.acceptance import evidence_body_sha256
from codex_base.release_verification import build_release_verification


def _manifest(
    tmp_path: Path,
    *,
    version: str = "0.1.1",
    repository: str = "https://github.com/K7-LS/codex-base",
) -> tuple[Path, Path, dict[str, object]]:
    asset = tmp_path / f"codex-base-{version}.zip"
    asset.write_bytes(b"accepted-candidate-bytes")
    manifest = {
        "schema_version": 1,
        "target": "codex",
        "version": version,
        "tag": f"codex-v{version}",
        "channel": "stable",
        "source": {
            "repository": repository,
        },
        "asset": {
            "name": asset.name,
            "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
            "bytes": asset.stat().st_size,
        },
    }
    path = tmp_path / "release-manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return path, asset, manifest


def test_release_verification_binds_immutable_release_and_exact_asset(
    tmp_path: Path,
):
    manifest_path, asset_path, manifest = _manifest(tmp_path)

    evidence = build_release_verification(
        manifest_path=manifest_path,
        asset_path=asset_path,
        release_api={
            "tag_name": manifest["tag"],
            "draft": False,
            "prerelease": False,
            "immutable": True,
        },
        release_attestation_output=b'{"verificationResult":"success"}\n',
        asset_attestation_output=b'{"verificationResult":"success"}\n',
        gh_version="gh version 2.96.0",
    )

    assert evidence["RELEASE_INTEGRITY"] == "PASS"
    assert evidence["repository"] == "K7-LS/codex-base"
    assert evidence["tag"] == "codex-v0.1.1"
    assert evidence["assets"] == [
        {
            "name": asset_path.name,
            "sha256": manifest["asset"]["sha256"],
            "bytes": manifest["asset"]["bytes"],
            "attestation": "PASS",
        }
    ]
    assert (
        evidence["evidence_body_sha256"]
        == evidence_body_sha256(evidence)
    )
    assert "verificationResult" not in str(evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("draft", True),
        ("prerelease", True),
        ("immutable", False),
        ("tag_name", "codex-v9.9.9"),
    ],
)
def test_release_verification_fails_closed_on_wrong_release_state(
    tmp_path: Path,
    field: str,
    value: object,
):
    manifest_path, asset_path, manifest = _manifest(tmp_path)
    release_api = {
        "tag_name": manifest["tag"],
        "draft": False,
        "prerelease": False,
        "immutable": True,
    }
    release_api[field] = value

    with pytest.raises(ValueError, match="release state"):
        build_release_verification(
            manifest_path=manifest_path,
            asset_path=asset_path,
            release_api=release_api,
            release_attestation_output=b"{}",
            asset_attestation_output=b"{}",
            gh_version="gh version 2.96.0",
        )


def test_release_verification_rejects_changed_local_asset(tmp_path: Path):
    manifest_path, asset_path, manifest = _manifest(tmp_path)
    asset_path.write_bytes(b"changed-after-acceptance")

    with pytest.raises(ValueError, match="asset binding"):
        build_release_verification(
            manifest_path=manifest_path,
            asset_path=asset_path,
            release_api={
                "tag_name": manifest["tag"],
                "draft": False,
                "prerelease": False,
                "immutable": True,
            },
            release_attestation_output=b"{}",
            asset_attestation_output=b"{}",
            gh_version="gh version 2.96.0",
        )


def test_release_verification_accepts_exact_legacy_bridge(tmp_path: Path):
    manifest_path, asset_path, manifest = _manifest(
        tmp_path,
        version="0.1.25",
        repository="https://github.com/daniileliseev1337/codex-base",
    )

    evidence = build_release_verification(
        manifest_path=manifest_path,
        asset_path=asset_path,
        release_api={
            "tag_name": manifest["tag"],
            "draft": False,
            "prerelease": False,
            "immutable": True,
        },
        release_attestation_output=b"{}",
        asset_attestation_output=b"{}",
        gh_version="gh version 2.96.0",
    )

    assert evidence["repository"] == "daniileliseev1337/codex-base"


def test_release_verification_rejects_legacy_identity_after_bridge(
    tmp_path: Path,
):
    manifest_path, asset_path, manifest = _manifest(
        tmp_path,
        version="0.1.26",
        repository="https://github.com/daniileliseev1337/codex-base",
    )

    with pytest.raises(ValueError, match="legacy repository identity"):
        build_release_verification(
            manifest_path=manifest_path,
            asset_path=asset_path,
            release_api={
                "tag_name": manifest["tag"],
                "draft": False,
                "prerelease": False,
                "immutable": True,
            },
            release_attestation_output=b"{}",
            asset_attestation_output=b"{}",
            gh_version="gh version 2.96.0",
        )
