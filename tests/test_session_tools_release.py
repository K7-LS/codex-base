from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from codex_base.acceptance import release_binding_from_manifest
from codex_base.release import build_release


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
        assert not any(
            name.startswith(".agents/skills/ru-writing-style/")
            for name in names
        )
        assert baseline["manifest_path"] == (
            "session-tools-baseline/session-tools-manifest.json"
        )
        assert baseline["manifest_sha256"] == hashlib.sha256(
            archive.read(baseline["manifest_path"])
        ).hexdigest()
        assert [tool["id"] for tool in baseline["tools"]] == [
            "ru-writing-style"
        ]
        assert "session-tools-baseline/tools/ru-writing-style/SKILL.md" in names


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
