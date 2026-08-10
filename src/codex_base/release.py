from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator

from .session_tools import (
    SessionToolsBuild,
    build_session_tools_bundle,
    session_tools_asset_record,
    session_tools_baseline_entries,
    validate_session_tools_release_binding,
)


SUPPORTED_CODEX_CLIENT = "0.146.0-alpha.3.1"
SOURCE_REPOSITORY = "https://github.com/daniileliseev1337/claude-base"
TARGET_REPOSITORY = "https://github.com/daniileliseev1337/codex-base"
TRANSFORMATION_ID = "codex-native-v1"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class ReleaseBuild:
    zip_path: Path
    manifest_path: Path
    component_lock_path: Path
    manifest: dict[str, object]


def bind_acceptance_evidence(
    manifest_path: Path,
    evidence_path: Path,
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("channel") != "candidate":
        raise ValueError("only a candidate manifest can be evidence-bound")
    manifest["acceptance_evidence_sha256"] = _sha256_bytes(
        evidence_path.read_bytes()
    )
    manifest_path.write_bytes(_json_bytes(manifest))
    return manifest


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _tree_files(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and "tests" not in path.parts
            and "__pycache__" not in path.parts
            and path.suffix.lower() not in {".pyc", ".pyo"}
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _git_output(repo_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git failed").strip()
        raise ValueError(f"Git source identity failed: {detail}")
    return result.stdout.strip()


def git_source_identity(repo_root: Path) -> dict[str, str]:
    return {
        "repository": TARGET_REPOSITORY,
        "commit": _git_output(repo_root, "rev-parse", "HEAD"),
        "tree": _git_output(repo_root, "rev-parse", "HEAD^{tree}"),
        "transformation": TRANSFORMATION_ID,
    }


def assert_clean_git_source(repo_root: Path) -> dict[str, str]:
    source_roots = (
        repo_root / "AGENTS.md",
        repo_root / "MIGRATION-SOURCE.json",
        repo_root / "agents",
        repo_root / "catalog",
        repo_root / "cold",
        repo_root / "control-skills",
        repo_root / "runtime",
        repo_root / "skills",
    )
    queue = list(source_roots)
    while queue:
        path = queue.pop()
        if not path.exists() and not path.is_symlink():
            raise ValueError(f"release source is missing: {path.name}")
        metadata = path.lstat()
        attributes = getattr(metadata, "st_file_attributes", 0)
        is_reparse = path.is_symlink() or bool(attributes & 0x400)
        if is_reparse:
            raise ValueError(
                f"release source contains a reparse point: {path}"
            )
        if path.is_dir():
            queue.extend(Path(entry.path) for entry in os.scandir(path))
    status = _git_output(
        repo_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if status:
        raise ValueError(
            "release acceptance requires a clean Git worktree"
        )
    return git_source_identity(repo_root)


@contextmanager
def _export_committed_tree(
    repo_root: Path,
    identity: dict[str, str],
) -> Iterator[Path]:
    commit = identity["commit"]
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "-z", commit],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if listing.returncode != 0:
        raise ValueError("Git tree inventory failed")
    tracked: set[str] = set()
    for record in listing.stdout.split(b"\0"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
            mode, object_type, _ = header.decode("ascii").split(" ", 2)
            relative = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("Git tree inventory is malformed") from exc
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise ValueError(
                f"release source contains a non-regular entry: {relative}"
            )
        if (
            not relative
            or PurePosixPath(relative).is_absolute()
            or ".." in PurePosixPath(relative).parts
            or "\\" in relative
        ):
            raise ValueError(f"release source path is unsafe: {relative}")
        tracked.add(relative)

    with tempfile.TemporaryDirectory(prefix="codex-base-git-tree-") as temporary:
        temporary_root = Path(temporary)
        archive_path = temporary_root / "source.zip"
        exported = subprocess.run(
            [
                "git",
                "archive",
                "--format=zip",
                f"--output={archive_path}",
                commit,
            ],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if exported.returncode != 0:
            raise ValueError("Git source export failed")
        source_root = temporary_root / "source"
        source_root.mkdir()
        seen: set[str] = set()
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if name not in tracked or name in seen:
                    raise ValueError(
                        f"Git archive differs from tree inventory: {name}"
                    )
                destination = source_root.joinpath(*PurePosixPath(name).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(info))
                seen.add(name)
        if seen != tracked:
            raise ValueError("Git archive is missing tracked source files")
        yield source_root


def _component_record(
    repo_root: Path,
    component_id: str,
    files: list[Path],
    source: dict[str, object],
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(repo_root).as_posix()
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(
            {
                "path": relative,
                "sha256": file_hash,
                "bytes": path.stat().st_size,
            }
        )
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return {
        "id": component_id,
        "source": source,
        "sha256": digest.hexdigest(),
        "files": rows,
    }


def build_component_lock(
    repo_root: Path,
    version: str,
    rendered_source: dict[str, str] | None = None,
) -> dict[str, object]:
    migration = json.loads(
        (repo_root / "MIGRATION-SOURCE.json").read_text(encoding="utf-8")
    )
    upstream = {
        "repository": str(migration["source"]["repository"]),
        "commit": str(migration["source"]["commit"]),
        "tree": str(migration["source"]["tree"]),
    }
    rendered = rendered_source or git_source_identity(repo_root)
    source = {
        "upstream_migration": upstream,
        "rendered_target": rendered,
    }
    agents_catalog = json.loads(
        (repo_root / "catalog" / "agents.json").read_text(encoding="utf-8")
    )
    skills_catalog = json.loads(
        (repo_root / "catalog" / "skills.json").read_text(encoding="utf-8")
    )
    cold_catalog = json.loads(
        (repo_root / "catalog" / "cold.json").read_text(encoding="utf-8")
    )

    agents = [
        _component_record(
            repo_root,
            str(item["id"]),
            [repo_root / str(item["source"])],
            source,
        )
        for item in agents_catalog
    ]
    skills = [
        _component_record(
            repo_root,
            str(item["id"]),
            _tree_files(repo_root / "skills" / str(item["id"])),
            source,
        )
        for item in skills_catalog
    ]
    control_skills = [
        _component_record(
            repo_root,
            path.name,
            _tree_files(path),
            source,
        )
        for path in sorted((repo_root / "control-skills").iterdir())
        if path.is_dir()
    ]
    cold_values = [
        value
        for group in ("memory", "chains", "commands")
        for value in cold_catalog[group]
    ]
    cold = [
        _component_record(
            repo_root,
            value,
            [repo_root / "cold" / value],
            source,
        )
        for value in cold_values
    ]
    runtime = [
        _component_record(
            repo_root,
            "runtime",
            _tree_files(repo_root / "runtime"),
            source,
        )
    ]
    return {
        "schema_version": 1,
        "target": "codex",
        "version": version,
        "provenance": source,
        "components": {
            "agents": agents,
            "skills": skills,
            "control_skills": control_skills,
            "cold": cold,
            "runtime": runtime,
        },
    }


def _add_tree(
    entries: dict[str, bytes],
    source_root: Path,
    destination_root: str,
    *,
    excluded_roots: frozenset[str] = frozenset(),
) -> None:
    for path in _tree_files(source_root):
        relative = path.relative_to(source_root).as_posix()
        if any(
            relative == root or relative.startswith(root + "/")
            for root in excluded_roots
        ):
            continue
        destination = str(PurePosixPath(destination_root) / relative)
        entries[destination] = path.read_bytes()


def _validate_foundation(
    foundation_root: Path,
) -> tuple[str, str]:
    required = (
        foundation_root / "VERSION",
        foundation_root / "foundation.ps1",
        foundation_root / "engine-manifest.json",
    )
    if not all(path.is_file() for path in required):
        raise ValueError("Foundation engine is missing required accepted files")
    version = (foundation_root / "VERSION").read_text(encoding="utf-8").strip()
    manifest = json.loads(
        (foundation_root / "engine-manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("engine_version") != version:
        raise ValueError("Foundation engine version and manifest disagree")
    if manifest.get("network") != "offline":
        raise ValueError("Foundation engine is not declared offline")
    if manifest.get("commands") != [
        "doctor",
        "install",
        "inventory",
        "plan",
        "rollback",
    ]:
        raise ValueError("Foundation engine command contract differs")
    if manifest.get("supported_powershell") != ["5.1", "7"]:
        raise ValueError("Foundation PowerShell contract differs")
    script_hash = _sha256_bytes(
        (foundation_root / "foundation.ps1").read_bytes()
    )
    if manifest.get("foundation_ps1_sha256") != script_hash:
        raise ValueError("Foundation engine SHA-256 mismatch")
    return version, _sha256_bytes(
        (foundation_root / "engine-manifest.json").read_bytes()
    )


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(
        path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, entries[name], compress_type=zipfile.ZIP_DEFLATED)


def build_release(
    repo_root: Path,
    dist_root: Path,
    version: str,
    foundation_root: Path,
) -> ReleaseBuild:
    foundation_version, foundation_manifest_sha256 = _validate_foundation(
        foundation_root
    )
    dist_root.mkdir(parents=True, exist_ok=True)
    identity = git_source_identity(repo_root)
    with _export_committed_tree(repo_root, identity) as source_root:
        component_lock = build_component_lock(
            source_root,
            version,
            rendered_source=identity,
        )
        session_tools = build_session_tools_bundle(
            source_root,
            dist_root,
            version,
        )
        return _build_release_from_export(
            source_root=source_root,
            dist_root=dist_root,
            version=version,
            foundation_root=foundation_root,
            foundation_version=foundation_version,
            foundation_manifest_sha256=foundation_manifest_sha256,
            component_lock=component_lock,
            identity=identity,
            session_tools=session_tools,
        )


def _build_release_from_export(
    *,
    source_root: Path,
    dist_root: Path,
    version: str,
    foundation_root: Path,
    foundation_version: str,
    foundation_manifest_sha256: str,
    component_lock: dict[str, object],
    identity: dict[str, str],
    session_tools: SessionToolsBuild,
) -> ReleaseBuild:
    component_lock_bytes = _json_bytes(component_lock)
    entries: dict[str, bytes] = {
        ".codex/AGENTS.md": (source_root / "AGENTS.md").read_bytes(),
        ".codex/config.toml": (
            source_root / "runtime" / "config.toml"
        ).read_bytes(),
        ".codex/hooks.json": (
            source_root / "runtime" / "hooks.json"
        ).read_bytes(),
        ".codex/base/VERSION": (version + "\n").encode("utf-8"),
        ".codex/base/components.lock.json": component_lock_bytes,
    }
    _add_tree(entries, source_root / "agents", ".codex/agents")
    session_tool_ids = frozenset(
        str(tool["id"])
        for tool in session_tools.manifest["tools"]
        if isinstance(tool, dict)
    )
    _add_tree(
        entries,
        source_root / "skills",
        ".agents/skills",
        excluded_roots=session_tool_ids,
    )
    _add_tree(entries, source_root / "control-skills", ".agents/skills")
    entries[".agents/skills/sync-base/runtime/connection.ps1"] = (
        source_root / "runtime" / "connection.ps1"
    ).read_bytes()
    entries.update(session_tools_baseline_entries(session_tools))
    _add_tree(entries, source_root / "cold", ".codex/base/cold")
    _add_tree(
        entries,
        source_root / "runtime" / "hooks",
        ".codex/base/runtime/hooks",
    )
    entries[".codex/base/runtime/connection.ps1"] = (
        source_root / "runtime" / "connection.ps1"
    ).read_bytes()
    entries[".codex/base/runtime/update-session-tools.ps1"] = (
        source_root / "runtime" / "update-session-tools.ps1"
    ).read_bytes()
    _add_tree(
        entries,
        foundation_root,
        f".codex/base/foundation/{foundation_version}",
    )

    package_files = [
        {
            "path": name,
            "sha256": _sha256_bytes(payload),
            "bytes": len(payload),
        }
        for name, payload in sorted(entries.items())
    ]
    individually_managed = sorted(
        name
        for name in entries
        if name.startswith((".agents/skills/", ".codex/agents/"))
    )
    replace_files = [
        name
        for name in individually_managed
        if not name.startswith(".agents/skills/")
    ]
    skill_directories = sorted(
        {
            str(PurePosixPath(*PurePosixPath(name).parts[:3]))
            for name in individually_managed
            if name.startswith(".agents/skills/")
        }
    )
    baseline = {
        "manifest_path": "session-tools-baseline/session-tools-manifest.json",
        "manifest_sha256": _sha256_bytes(session_tools.manifest_bytes),
        "tools": session_tools.manifest["tools"],
        "retired_tool_ids": [],
    }
    package_manifest = {
        "schema_version": 1,
        "target": "codex",
        "version": version,
        "client": {
            "id": "codex-cli",
            "supported_version": SUPPORTED_CODEX_CLIENT,
        },
        "foundation_engine_version": foundation_version,
        "managed_surface": {
            "exact_directories": sorted(
                [
                    ".codex/base/cold",
                    ".codex/base/foundation",
                    ".codex/base/runtime",
                    *skill_directories,
                ]
            ),
            "replace_files": sorted(
                replace_files
                + [
                    ".codex/AGENTS.md",
                    ".codex/base/VERSION",
                    ".codex/base/components.lock.json",
                    ".codex/hooks.json",
                ]
            ),
            "merge_toml_files": [".codex/config.toml"],
            "preserved_paths": [
                ".codex/archived_sessions",
                ".codex/auth.json",
                ".codex/browser",
                ".codex/computer-use",
                ".codex/imports",
                ".codex/memories",
                ".codex/sessions",
                ".codex/state",
                ".codex/state.sqlite",
            ],
        },
        "sync_policy": {
            "direction": "hub-to-consumer",
            "consumer_feedback_upload": False,
            "consumer_push": False,
            "consumer_session_upload": False,
            "credentials_included": False,
        },
        "environment": {
            "scope": "current-user",
            "set": [],
        },
        "session_tools_baseline": baseline,
        "files": package_files,
    }
    package_manifest_bytes = _json_bytes(package_manifest)
    entries["package-manifest.json"] = package_manifest_bytes

    zip_path = dist_root / f"codex-base-{version}.zip"
    _write_zip(zip_path, entries)
    zip_payload = zip_path.read_bytes()
    release_manifest = {
        "schema_version": 1,
        "target": "codex",
        "version": version,
        "tag": f"codex-v{version}",
        "channel": "candidate",
        "client": {
            "id": "codex-cli",
            "supported_version": SUPPORTED_CODEX_CLIENT,
        },
        "foundation_engine_version": foundation_version,
        "foundation_engine_manifest_sha256": foundation_manifest_sha256,
        "source": identity,
        "asset": {
            "name": zip_path.name,
            "sha256": _sha256_bytes(zip_payload),
            "bytes": len(zip_payload),
        },
        "package_manifest_sha256": _sha256_bytes(package_manifest_bytes),
        "components_lock_sha256": _sha256_bytes(component_lock_bytes),
        "session_tools_asset": session_tools_asset_record(session_tools),
        "requires": {
            "immutable_release": True,
            "release_attestation": True,
            "verification_commands": [
                f"gh release verify codex-v{version} -R daniileliseev1337/codex-base",
                (
                    f"gh release verify-asset codex-v{version} "
                    f"{zip_path.name} -R daniileliseev1337/codex-base"
                ),
            ],
        },
    }
    validate_session_tools_release_binding(
        release_manifest=release_manifest,
        package_manifest=package_manifest,
        session_asset_path=session_tools.zip_path,
        package_archive_path=zip_path,
    )
    manifest_path = dist_root / "release-manifest.json"
    lock_path = dist_root / "components.lock.json"
    manifest_path.write_bytes(_json_bytes(release_manifest))
    lock_path.write_bytes(component_lock_bytes)
    return ReleaseBuild(
        zip_path=zip_path,
        manifest_path=manifest_path,
        component_lock_path=lock_path,
        manifest=release_manifest,
    )
