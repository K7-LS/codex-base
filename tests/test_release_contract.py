from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from codex_base.release import (
    SUPPORTED_CODEX_CLIENT,
    assert_clean_git_source,
    build_component_lock,
    build_release,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_foundation(root: Path) -> Path:
    root.mkdir()
    (root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    script = root / "foundation.ps1"
    script.write_text(
        "param([string]$Command)\nWrite-Output $Command\n",
        encoding="utf-8",
    )
    (root / "engine-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "engine_version": "0.1.0",
                "protocol_version": 1,
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


def test_component_lock_covers_all_vendored_runtime_components(repo_root):
    lock = build_component_lock(repo_root, "0.1.0")

    assert lock["schema_version"] == 1
    assert lock["target"] == "codex"
    assert lock["version"] == "0.1.0"
    assert len(lock["components"]["agents"]) == 16
    assert len(lock["components"]["skills"]) == 38
    assert len(lock["components"]["control_skills"]) == 1
    assert len(lock["components"]["cold"]) == 26
    assert len(lock["components"]["runtime"]) == 1
    runtime_paths = {
        row["path"]
        for row in lock["components"]["runtime"][0]["files"]
    }
    assert "runtime/connection.ps1" in runtime_paths
    rendered = lock["provenance"]["rendered_target"]
    assert rendered["repository"].endswith("/codex-base")
    assert len(rendered["commit"]) == 40
    assert len(rendered["tree"]) == 40
    assert rendered["transformation"] == "codex-native-v1"
    for group in ("agents", "skills", "cold"):
        for component in lock["components"][group]:
            assert component["source"]["upstream_migration"][
                "repository"
            ].endswith("/claude-base")
            assert component["source"]["rendered_target"] == rendered
            assert len(component["sha256"]) == 64
            assert component["files"]


def test_release_zip_is_deterministic_native_and_exactly_mapped(repo_root, tmp_path):
    foundation = _fake_foundation(tmp_path / "foundation")
    first = build_release(repo_root, tmp_path / "one", "0.1.0", foundation)
    second = build_release(repo_root, tmp_path / "two", "0.1.0", foundation)

    assert _sha256(first.zip_path) == _sha256(second.zip_path)
    assert first.manifest == second.manifest
    assert first.manifest["supported_codex_client"] == SUPPORTED_CODEX_CLIENT
    assert first.manifest["asset"]["sha256"] == _sha256(first.zip_path)
    assert first.manifest["components_lock_sha256"] == _sha256(
        first.component_lock_path
    )
    source = first.manifest["source"]
    assert source["commit"] == subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    assert source["tree"] == subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()

    with zipfile.ZipFile(first.zip_path) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
        assert ".codex/AGENTS.md" in names
        assert ".codex/config.toml" in names
        assert ".codex/hooks.json" in names
        assert ".codex/base/VERSION" in names
        assert "package-manifest.json" in names
        assert ".codex/base/components.lock.json" in names
        assert ".codex/base/foundation/0.1.0/foundation.ps1" in names
        assert ".codex/base/runtime/connection.ps1" in names
        assert ".agents/skills/sync-base/SKILL.md" in names
        assert len([name for name in names if name.startswith(".codex/agents/")]) == 16
        assert (
            len(
                [
                    name
                    for name in names
                    if name.startswith(".agents/skills/")
                    and name.endswith("/SKILL.md")
                    and "/sync-base/" not in name
                ]
            )
            == 38
        )
        assert not any("/tests/" in name or "__pycache__" in name for name in names)

        package_manifest = json.loads(
            archive.read("package-manifest.json")
        )
        assert package_manifest["client"] == {
            "id": "codex-cli",
            "supported_version": SUPPORTED_CODEX_CLIENT,
        }
        assert "supported_codex_client" not in package_manifest
        managed_surface = package_manifest["managed_surface"]
        assert managed_surface["exact_directories"] == [
            ".codex/base/cold",
            ".codex/base/foundation",
            ".codex/base/runtime",
        ]
        assert managed_surface["merge_toml_files"] == [
            ".codex/config.toml"
        ]
        individually_managed = {
            name
            for name in names
            if name.startswith((".agents/skills/", ".codex/agents/"))
        }
        assert set(managed_surface["replace_files"]) == individually_managed | {
            ".codex/AGENTS.md",
            ".codex/base/VERSION",
            ".codex/base/components.lock.json",
            ".codex/hooks.json",
        }
        assert managed_surface["replace_files"] == sorted(
            managed_surface["replace_files"]
        )
        assert managed_surface["preserved_paths"] == [
                ".codex/archived_sessions",
                ".codex/auth.json",
                ".codex/browser",
                ".codex/computer-use",
                ".codex/imports",
                ".codex/memories",
                ".codex/sessions",
                ".codex/state",
                ".codex/state.sqlite",
            ]
        assert package_manifest["sync_policy"] == {
            "direction": "hub-to-consumer",
            "consumer_feedback_upload": False,
            "consumer_push": False,
            "consumer_session_upload": False,
            "credentials_included": False,
        }
        assert package_manifest["environment"] == {
            "scope": "current-user",
            "set": [],
        }
        assert archive.read(
            ".codex/base/components.lock.json"
        ) == first.component_lock_path.read_bytes()

        for name in names:
            if Path(name).suffix.lower() not in {
                ".md",
                ".txt",
                ".py",
                ".ps1",
                ".json",
                ".toml",
                ".yaml",
                ".yml",
                ".tmpl",
            }:
                continue
            text = archive.read(name).decode("utf-8")
            assert ".claude/" not in text.lower()
            assert ".claude\\" not in text.lower()
            assert "CLAUDE.md" not in text
            assert "AskUserQuestion" not in text


def test_release_fails_closed_without_accepted_foundation_engine(repo_root, tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="Foundation"):
        build_release(repo_root, tmp_path / "dist", "0.1.0", missing)


def test_release_rejects_foundation_engine_hash_mismatch(repo_root, tmp_path):
    foundation = _fake_foundation(tmp_path / "foundation")
    (foundation / "foundation.ps1").write_text(
        "Write-Output 'tampered'\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="SHA-256"):
        build_release(
            repo_root,
            tmp_path / "dist",
            "0.1.0",
            foundation,
        )


def test_release_uses_committed_git_tree_and_clean_gate_rejects_ambient_changes(
    repo_root, tmp_path
):
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", str(repo_root), str(clone)],
        check=True,
    )
    committed_agents = (clone / "AGENTS.md").read_bytes()
    (clone / "AGENTS.md").write_text("# uncommitted replacement\n", encoding="utf-8")
    untracked = clone / "skills" / "ambient-only" / "SKILL.md"
    untracked.parent.mkdir()
    untracked.write_text("ambient\n", encoding="utf-8")
    foundation = _fake_foundation(tmp_path / "foundation")

    with pytest.raises(ValueError, match="clean Git worktree"):
        assert_clean_git_source(clone)
    built = build_release(clone, tmp_path / "dist", "0.1.0", foundation)

    with zipfile.ZipFile(built.zip_path) as archive:
        assert archive.read(".codex/AGENTS.md") == committed_agents
        assert not any("ambient-only" in name for name in archive.namelist())


def test_clean_release_gate_rejects_reparse_point_in_managed_source(
    repo_root, tmp_path
):
    executable = shutil.which("pwsh") or shutil.which("powershell.exe")
    if not executable:
        pytest.skip("PowerShell is unavailable")
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", str(repo_root), str(clone)],
        check=True,
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    link = clone / "skills" / "reparse-source"
    created = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-Command",
            (
                "New-Item -ItemType Junction -Path "
                f"'{link}' -Target '{outside}' | Out-Null"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if created.returncode != 0:
        pytest.skip(f"junction unavailable: {created.stderr}")

    with pytest.raises(ValueError, match="reparse point"):
        assert_clean_git_source(clone)


def test_migration_source_is_pinned_and_complete(repo_root):
    source = json.loads(
        (repo_root / "MIGRATION-SOURCE.json").read_text(encoding="utf-8")
    )
    assert source["source"]["repository"] == (
        "https://github.com/daniileliseev1337/claude-base"
    )
    assert source["source"]["commit"] == "d263065d902000a032c87bd31175889168f616bc"
    assert source["source"]["tree"] == "7e3fda8ff712e22bb1d5a2bb533bd7a6998cc474"
    assert len(source["inventory"]["agents"]) == 16
    assert len(source["inventory"]["skills"]) == 38
    assert len(source["inventory"]["cold"]) == 26
