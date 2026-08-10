from __future__ import annotations

import hashlib
import json
import warnings
import zipfile
from pathlib import Path

import pytest

from codex_base.acceptance import release_binding_from_manifest
from codex_base.release import build_release
from codex_base.session_tools import (
    SessionToolsBuild,
    build_session_tools_bundle,
    session_tools_asset_record,
    validate_session_tools_release_binding,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _foundation(root: Path) -> Path:
    root.mkdir()
    script = root / "foundation.ps1"
    script.write_text("exit 0\n", encoding="utf-8")
    (root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (root / "engine-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "protocol_version": 1,
                "engine_version": "0.1.0",
                "network": "offline",
                "commands": [
                    "doctor",
                    "install",
                    "inventory",
                    "plan",
                    "rollback",
                ],
                "supported_powershell": ["5.1", "7"],
                "foundation_ps1_sha256": _sha256(script),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def _copy_package_with_entries(
    source: Path,
    destination: Path,
    transform,
) -> Path:
    with zipfile.ZipFile(source) as archive:
        entries = [
            (info.filename, archive.read(info))
            for info in archive.infolist()
        ]
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:")
        with zipfile.ZipFile(destination, "w") as archive:
            for name, payload in transform(entries):
                archive.writestr(name, payload)
    return destination


def test_release_binds_session_asset_and_keeps_session_skill_out_of_base(
    repo_root: Path, tmp_path: Path
):
    built = build_release(
        repo_root,
        tmp_path / "dist",
        "0.1.4",
        _foundation(tmp_path / "foundation"),
    )
    session = built.manifest["session_tools_asset"]

    assert session["name"] == "session-tools-codex-0.1.4.zip"
    assert session["sha256"] == _sha256(tmp_path / "dist" / session["name"])
    assert session["tool_count"] == 1
    assert session["file_count"] == 1
    assert release_binding_from_manifest(built.manifest)["session_tools_asset"] == session

    with zipfile.ZipFile(built.zip_path) as archive:
        names = archive.namelist()
        package = json.loads(archive.read("package-manifest.json"))
        baseline = package["session_tools_baseline"]
        baseline_manifest_bytes = archive.read(baseline["manifest_path"])
        assert not any(
            name.startswith(".agents/skills/ru-writing-style/")
            for name in names
        )
        assert baseline["manifest_path"] == (
            "session-tools-baseline/session-tools-manifest.json"
        )
        assert baseline["manifest_sha256"] == hashlib.sha256(
            baseline_manifest_bytes
        ).hexdigest()
        assert [tool["id"] for tool in baseline["tools"]] == [
            "ru-writing-style"
        ]
        assert "session-tools-baseline/tools/ru-writing-style/SKILL.md" in names
    assert validate_session_tools_release_binding(
        release_manifest=built.manifest,
        package_manifest=package,
        session_asset_path=tmp_path / "dist" / session["name"],
        package_archive_path=built.zip_path,
    )["tools"] == baseline["tools"]


def test_release_owns_each_base_skill_without_claiming_unknown_local_skills(
    repo_root: Path, tmp_path: Path
):
    built = build_release(
        repo_root,
        tmp_path / "dist",
        "0.1.4",
        _foundation(tmp_path / "foundation"),
    )
    with zipfile.ZipFile(built.zip_path) as archive:
        package = json.loads(archive.read("package-manifest.json"))

    exact = package["managed_surface"]["exact_directories"]
    assert ".agents/skills" not in exact
    assert ".agents/skills/sync-base" in exact
    assert ".agents/skills/ru-writing-style" not in exact
    assert exact == sorted(exact)
    assert all(
        path.startswith(".agents/skills/")
        for path in exact
        if path.startswith(".agents/skills/")
    )


def test_legacy_release_manifest_remains_readable_without_session_asset():
    legacy = {
        "target": "codex",
        "version": "0.1.3",
        "tag": "codex-v0.1.3",
        "asset": {"name": "codex-base-0.1.3.zip"},
        "package_manifest_sha256": "1" * 64,
        "components_lock_sha256": "2" * 64,
        "source": {"commit": "3" * 40},
        "foundation_engine_version": "0.1.0",
        "foundation_engine_manifest_sha256": "4" * 64,
    }

    assert release_binding_from_manifest(legacy) == legacy


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("version", "9.9.9", "asset name"),
        ("tag", "codex-v9.9.9", "tag and version"),
    ],
)
def test_release_binding_rejects_mixed_outer_session_identity(
    repo_root: Path,
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
):
    built = build_release(
        repo_root,
        tmp_path / "dist",
        "0.1.4",
        _foundation(tmp_path / "foundation"),
    )
    mixed = dict(built.manifest)
    mixed[field] = value

    with pytest.raises(ValueError, match=message):
        release_binding_from_manifest(mixed)


@pytest.mark.parametrize("field", ["release_tag", "base_version"])
def test_session_binding_rejects_internal_manifest_identity_mismatch(
    repo_root: Path,
    tmp_path: Path,
    field: str,
):
    original = build_session_tools_bundle(
        repo_root,
        tmp_path / "original",
        "0.1.4",
    )
    with zipfile.ZipFile(original.zip_path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["session-tools-manifest.json"])
    manifest[field] = "codex-v9.9.9" if field == "release_tag" else "9.9.9"
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    entries["session-tools-manifest.json"] = manifest_bytes
    mixed_path = tmp_path / "session-tools-codex-0.1.4.zip"
    with zipfile.ZipFile(mixed_path, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    mixed = SessionToolsBuild(mixed_path, manifest_bytes, manifest)
    release_manifest = {
        "version": "0.1.4",
        "tag": "codex-v0.1.4",
        "session_tools_asset": session_tools_asset_record(mixed),
    }
    package_manifest = {
        "target": "codex",
        "version": "0.1.4",
        "session_tools_baseline": {
            "manifest_path": "session-tools-baseline/session-tools-manifest.json",
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "tools": manifest["tools"],
            "retired_tool_ids": [],
        },
    }

    with pytest.raises(ValueError, match="identity differs"):
        validate_session_tools_release_binding(
            release_manifest=release_manifest,
            package_manifest=package_manifest,
            session_asset_path=mixed_path,
            package_archive_path=tmp_path / "unused-package.zip",
        )


@pytest.mark.parametrize("tamper", ["manifest_sha256", "tools"])
def test_session_binding_rejects_mixed_package_baseline(
    repo_root: Path,
    tmp_path: Path,
    tamper: str,
):
    built = build_release(
        repo_root,
        tmp_path / "dist",
        "0.1.4",
        _foundation(tmp_path / "foundation"),
    )
    with zipfile.ZipFile(built.zip_path) as archive:
        package = json.loads(archive.read("package-manifest.json"))
    package = json.loads(json.dumps(package))
    if tamper == "manifest_sha256":
        package["session_tools_baseline"]["manifest_sha256"] = "0" * 64
    else:
        package["session_tools_baseline"]["tools"] = []

    with pytest.raises(ValueError, match="baseline"):
        validate_session_tools_release_binding(
            release_manifest=built.manifest,
            package_manifest=package,
            session_asset_path=(
                tmp_path
                / "dist"
                / built.manifest["session_tools_asset"]["name"]
            ),
            package_archive_path=built.zip_path,
        )


@pytest.mark.parametrize(
    "tamper",
    [
        "payload",
        "missing",
        "extra",
        "duplicate",
        "casefold_collision",
        "unsafe",
    ],
)
def test_session_binding_rejects_invalid_package_baseline_members(
    repo_root: Path,
    tmp_path: Path,
    tamper: str,
):
    built = build_release(
        repo_root,
        tmp_path / "dist",
        "0.1.4",
        _foundation(tmp_path / "foundation"),
    )
    with zipfile.ZipFile(built.zip_path) as archive:
        package = json.loads(archive.read("package-manifest.json"))
    target = "session-tools-baseline/tools/ru-writing-style/SKILL.md"

    def transform(entries: list[tuple[str, bytes]]):
        if tamper == "payload":
            return [
                (name, b"tampered\n" if name == target else payload)
                for name, payload in entries
            ]
        if tamper == "missing":
            return [(name, payload) for name, payload in entries if name != target]
        if tamper == "duplicate":
            payload = next(payload for name, payload in entries if name == target)
            return [*entries, (target, payload)]
        addition = {
            "extra": (
                "session-tools-baseline/tools/ru-writing-style/extra.md",
                b"extra\n",
            ),
            "casefold_collision": (
                "session-tools-baseline/tools/ru-writing-style/skill.md",
                b"collision\n",
            ),
            "unsafe": (
                "session-tools-baseline/tools/ru-writing-style/../escape.md",
                b"unsafe\n",
            ),
        }[tamper]
        return [*entries, addition]

    package_path = _copy_package_with_entries(
        built.zip_path,
        tmp_path / f"package-{tamper}.zip",
        transform,
    )
    with pytest.raises(ValueError, match="baseline"):
        validate_session_tools_release_binding(
            release_manifest=built.manifest,
            package_manifest=package,
            session_asset_path=(
                tmp_path
                / "dist"
                / built.manifest["session_tools_asset"]["name"]
            ),
            package_archive_path=package_path,
        )


@pytest.mark.parametrize("field", ["sha256", "bytes"])
def test_session_binding_rejects_mixed_package_baseline_file_record(
    repo_root: Path,
    tmp_path: Path,
    field: str,
):
    built = build_release(
        repo_root,
        tmp_path / "dist",
        "0.1.4",
        _foundation(tmp_path / "foundation"),
    )
    with zipfile.ZipFile(built.zip_path) as archive:
        package = json.loads(archive.read("package-manifest.json"))
    package = json.loads(json.dumps(package))
    target = "session-tools-baseline/tools/ru-writing-style/SKILL.md"
    record = next(row for row in package["files"] if row["path"] == target)
    record[field] = "0" * 64 if field == "sha256" else record["bytes"] + 1

    with pytest.raises(ValueError, match="baseline file record"):
        validate_session_tools_release_binding(
            release_manifest=built.manifest,
            package_manifest=package,
            session_asset_path=(
                tmp_path
                / "dist"
                / built.manifest["session_tools_asset"]["name"]
            ),
            package_archive_path=built.zip_path,
        )
