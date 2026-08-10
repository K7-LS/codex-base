from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MAX_TOOLS = 32
MAX_FILES = 256
MAX_FILE_BYTES = 1024 * 1024
MAX_EXPANDED_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MANIFEST_NAME = "session-tools-manifest.json"
BASELINE_MANIFEST_PATH = f"session-tools-baseline/{MANIFEST_NAME}"
_ALLOWED_SUFFIXES = {".json", ".md", ".toml", ".txt", ".yaml", ".yml"}
_TOOL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class SessionToolsBuild:
    zip_path: Path
    manifest_bytes: bytes
    manifest: dict[str, object]


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json_bytes(payload: bytes) -> dict[str, Any]:
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError("session tools manifest must not have a UTF-8 BOM")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("session tools manifest is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("session tools manifest must be an object")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} has unknown or missing fields")


def _is_safe_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and not any(part.endswith(":") for part in path.parts)
        and path.name not in {"", ".", ".."}
    )


def _validate_file_record(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("session tool file record must be an object")
    _require_exact_keys(value, {"path", "sha256", "bytes"}, "session tool file record")
    path = value["path"]
    size = value["bytes"]
    digest = value["sha256"]
    if not _is_safe_relative_path(path):
        raise ValueError("session tool file path is unsafe")
    if PurePosixPath(str(path)).suffix.lower() not in _ALLOWED_SUFFIXES:
        raise ValueError("session tool file extension is not declarative")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError("session tool file size is invalid")
    if size > MAX_FILE_BYTES:
        raise ValueError("session tool file size limit exceeded")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ValueError("session tool file SHA-256 is invalid")
    return {"path": path, "sha256": digest, "bytes": size}


def validate_session_tools_manifest(
    payload: bytes,
    *,
    expected_release_tag: str | None = None,
    expected_base_version: str | None = None,
) -> dict[str, object]:
    manifest = _load_json_bytes(payload)
    _require_exact_keys(
        manifest,
        {"schema_version", "target", "release_tag", "base_version", "tools"},
        "session tools manifest",
    )
    if manifest["schema_version"] != 1:
        raise ValueError("session tools manifest schema version differs")
    if manifest["target"] != "codex":
        raise ValueError("session tools manifest target differs")
    if not isinstance(manifest["release_tag"], str) or not manifest["release_tag"]:
        raise ValueError("session tools manifest release tag is invalid")
    if not isinstance(manifest["base_version"], str) or not manifest["base_version"]:
        raise ValueError("session tools manifest base version is invalid")
    if manifest["release_tag"] != f"codex-v{manifest['base_version']}":
        raise ValueError("session tools manifest identity differs")
    if (
        expected_release_tag is not None
        and manifest["release_tag"] != expected_release_tag
    ) or (
        expected_base_version is not None
        and manifest["base_version"] != expected_base_version
    ):
        raise ValueError("session tools manifest identity differs")
    tools = manifest["tools"]
    if not isinstance(tools, list) or len(tools) > MAX_TOOLS:
        raise ValueError("session tools manifest tool limit exceeded")

    normalized_ids: set[str] = set()
    previous_id = ""
    total_files = 0
    expanded_bytes = 0
    parsed_tools: list[dict[str, object]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            raise ValueError("session tool record must be an object")
        _require_exact_keys(tool, {"id", "files"}, "session tool record")
        tool_id = tool["id"]
        if not isinstance(tool_id, str) or not _TOOL_ID.fullmatch(tool_id):
            raise ValueError("session tool id is invalid")
        normalized_id = tool_id.casefold()
        if normalized_id in normalized_ids:
            raise ValueError("session tool id has a Windows case collision")
        if previous_id and tool_id <= previous_id:
            raise ValueError("session tools are not sorted")
        normalized_ids.add(normalized_id)
        previous_id = tool_id
        files = tool["files"]
        if not isinstance(files, list) or not files:
            raise ValueError("session tool must have files")
        normalized_paths: set[str] = set()
        previous_path = ""
        parsed_files: list[dict[str, object]] = []
        for record in files:
            parsed = _validate_file_record(record)
            relative = str(parsed["path"])
            normalized_path = relative.casefold()
            if normalized_path in normalized_paths:
                raise ValueError("session tool file path has a Windows case collision")
            if previous_path and relative <= previous_path:
                raise ValueError("session tool files are not sorted")
            normalized_paths.add(normalized_path)
            previous_path = relative
            total_files += 1
            expanded_bytes += int(parsed["bytes"])
            parsed_files.append(parsed)
        parsed_tools.append({"id": tool_id, "files": parsed_files})
    if total_files > MAX_FILES:
        raise ValueError("session tools manifest file limit exceeded")
    if expanded_bytes > MAX_EXPANDED_BYTES:
        raise ValueError("session tools manifest expanded size limit exceeded")
    return {
        "schema_version": 1,
        "target": "codex",
        "release_tag": manifest["release_tag"],
        "base_version": manifest["base_version"],
        "tools": parsed_tools,
    }


def _zip_info_is_unsafe(info: zipfile.ZipInfo) -> str | None:
    if info.is_dir():
        return "directory"
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        return "symlink"
    if mode and mode & 0o111:
        return "executable"
    return None


def validate_session_tools_archive(
    archive_path: Path,
    *,
    manifest_sha256: str | None = None,
    expected_release_tag: str | None = None,
    expected_base_version: str | None = None,
) -> dict[str, object]:
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("session tools ZIP size limit exceeded")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            if archive.comment:
                raise ValueError("session tools ZIP comment is not allowed")
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if sum(info.file_size for info in infos) > MAX_EXPANDED_BYTES:
                raise ValueError("session tools ZIP expanded size limit exceeded")
            if names.count(MANIFEST_NAME) != 1:
                raise ValueError("session tools manifest is missing or duplicated")
            normalized_names: set[str] = set()
            seen_names: set[str] = set()
            for info in infos:
                unsafe = _zip_info_is_unsafe(info)
                if unsafe:
                    raise ValueError(f"session tools ZIP contains {unsafe} entry")
                if not _is_safe_relative_path(info.filename):
                    raise ValueError("session tools ZIP path is unsafe")
                if info.filename in seen_names:
                    raise ValueError("session tools ZIP has a duplicate ZIP member")
                normalized = info.filename.casefold()
                if normalized in normalized_names:
                    raise ValueError("session tools ZIP has a Windows case collision")
                seen_names.add(info.filename)
                normalized_names.add(normalized)
            manifest_bytes = archive.read(MANIFEST_NAME)
            if (
                manifest_sha256 is not None
                and hashlib.sha256(manifest_bytes).hexdigest()
                != manifest_sha256
            ):
                raise ValueError("session tools manifest SHA-256 differs")
            manifest = validate_session_tools_manifest(
                manifest_bytes,
                expected_release_tag=expected_release_tag,
                expected_base_version=expected_base_version,
            )
            expected: dict[str, dict[str, object]] = {MANIFEST_NAME: {}}
            for tool in manifest["tools"]:
                assert isinstance(tool, dict)
                for record in tool["files"]:
                    assert isinstance(record, dict)
                    name = f"tools/{tool['id']}/{record['path']}"
                    expected[name] = record
            if set(names) != set(expected):
                raise ValueError("session tools ZIP has unexpected or missing entries")
            for name, record in expected.items():
                if name == MANIFEST_NAME:
                    continue
                payload = archive.read(name)
                if len(payload) != record["bytes"]:
                    raise ValueError("session tools ZIP file size differs")
                if hashlib.sha256(payload).hexdigest() != record["sha256"]:
                    raise ValueError("session tools ZIP file SHA-256 differs")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("session tools ZIP is unreadable") from exc
    return manifest


def _source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    queue = [root]
    while queue:
        current = queue.pop()
        for entry in os.scandir(current):
            path = Path(entry.path)
            metadata = entry.stat(follow_symlinks=False)
            attributes = getattr(metadata, "st_file_attributes", 0)
            if stat.S_ISLNK(metadata.st_mode) or attributes & 0x400:
                raise ValueError(f"session tool source contains symlink: {path}")
            if entry.is_dir(follow_symlinks=False):
                queue.append(path)
                continue
            if not entry.is_file(follow_symlinks=False):
                raise ValueError(f"session tool source is not a regular file: {path}")
            if metadata.st_mode & 0o111:
                raise ValueError(f"session tool source contains executable: {path}")
            if path.suffix.lower() not in _ALLOWED_SUFFIXES:
                raise ValueError(f"session tool source extension is not declarative: {path}")
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


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
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, entries[name], compress_type=zipfile.ZIP_DEFLATED)


def build_session_tools_bundle(
    repo_root: Path,
    dist_root: Path,
    base_version: str,
    *,
    tool_ids: tuple[str, ...] = ("ru-writing-style",),
) -> SessionToolsBuild:
    if not base_version:
        raise ValueError("session tools base version is required")
    if not tool_ids or tuple(sorted(tool_ids)) != tool_ids:
        raise ValueError("session tool ids must be a non-empty sorted tuple")
    entries: dict[str, bytes] = {}
    tools: list[dict[str, object]] = []
    for tool_id in tool_ids:
        if not _TOOL_ID.fullmatch(tool_id):
            raise ValueError("session tool id is invalid")
        source_root = repo_root / "skills" / tool_id
        if not source_root.is_dir() or source_root.is_symlink():
            raise ValueError(f"session tool source is missing or unsafe: {tool_id}")
        files = _source_files(source_root)
        if not files:
            raise ValueError(f"session tool source has no files: {tool_id}")
        records: list[dict[str, object]] = []
        for path in files:
            relative = path.relative_to(source_root).as_posix()
            payload = path.read_bytes()
            record = {
                "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
            records.append(record)
            entries[f"tools/{tool_id}/{relative}"] = payload
        tools.append({"id": tool_id, "files": records})
    manifest = validate_session_tools_manifest(
        _json_bytes(
            {
                "schema_version": 1,
                "target": "codex",
                "release_tag": f"codex-v{base_version}",
                "base_version": base_version,
                "tools": tools,
            }
        ),
        expected_release_tag=f"codex-v{base_version}",
        expected_base_version=base_version,
    )
    manifest_bytes = _json_bytes(manifest)
    entries[MANIFEST_NAME] = manifest_bytes
    dist_root.mkdir(parents=True, exist_ok=True)
    zip_path = dist_root / f"session-tools-codex-{base_version}.zip"
    _write_zip(zip_path, entries)
    validate_session_tools_archive(zip_path)
    return SessionToolsBuild(zip_path, manifest_bytes, manifest)


def session_tools_baseline_entries(bundle: SessionToolsBuild) -> dict[str, bytes]:
    entries = {BASELINE_MANIFEST_PATH: bundle.manifest_bytes}
    with zipfile.ZipFile(bundle.zip_path) as archive:
        for tool in bundle.manifest["tools"]:
            assert isinstance(tool, dict)
            for record in tool["files"]:
                assert isinstance(record, dict)
                name = f"tools/{tool['id']}/{record['path']}"
                entries[f"session-tools-baseline/{name}"] = archive.read(name)
    return entries


def session_tools_asset_record(bundle: SessionToolsBuild) -> dict[str, object]:
    return {
        "name": bundle.zip_path.name,
        "sha256": hashlib.sha256(bundle.zip_path.read_bytes()).hexdigest(),
        "bytes": bundle.zip_path.stat().st_size,
        "manifest_sha256": hashlib.sha256(bundle.manifest_bytes).hexdigest(),
        "tool_count": len(bundle.manifest["tools"]),
        "file_count": sum(
            len(tool["files"])
            for tool in bundle.manifest["tools"]
            if isinstance(tool, dict)
        ),
    }


def validate_session_tools_asset_record(
    value: object,
    *,
    expected_version: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("session tools asset record must be an object")
    _require_exact_keys(
        value,
        {"name", "sha256", "bytes", "manifest_sha256", "tool_count", "file_count"},
        "session tools asset record",
    )
    name = value["name"]
    expected_name = f"session-tools-codex-{expected_version}.zip"
    if name != expected_name:
        raise ValueError("session tools asset name is invalid")
    for key in ("sha256", "manifest_sha256"):
        if not isinstance(value[key], str) or not _SHA256.fullmatch(value[key]):
            raise ValueError(f"session tools asset {key} is invalid")
    for key, limit in (("bytes", MAX_ARCHIVE_BYTES), ("tool_count", MAX_TOOLS), ("file_count", MAX_FILES)):
        number = value[key]
        if not isinstance(number, int) or isinstance(number, bool) or number <= 0 or number > limit:
            raise ValueError(f"session tools asset {key} is invalid")
    return dict(value)


def validate_session_tools_release_binding(
    *,
    release_manifest: dict[str, object],
    package_manifest: dict[str, object],
    session_asset_path: Path,
    baseline_manifest_bytes: bytes,
) -> dict[str, object]:
    version = release_manifest.get("version")
    tag = release_manifest.get("tag")
    if not isinstance(version, str) or not version:
        raise ValueError("session tools release version is invalid")
    asset = validate_session_tools_asset_record(
        release_manifest.get("session_tools_asset"),
        expected_version=version,
    )
    if tag != f"codex-v{version}":
        raise ValueError("session tools release tag and version differ")
    if session_asset_path.name != asset["name"]:
        raise ValueError("session tools asset path differs")
    asset_bytes = session_asset_path.read_bytes()
    if len(asset_bytes) != asset["bytes"]:
        raise ValueError("session tools asset byte count differs")
    if hashlib.sha256(asset_bytes).hexdigest() != asset["sha256"]:
        raise ValueError("session tools asset SHA-256 differs")
    manifest = validate_session_tools_archive(
        session_asset_path,
        manifest_sha256=str(asset["manifest_sha256"]),
        expected_release_tag=str(tag),
        expected_base_version=version,
    )
    if (
        manifest["release_tag"] != tag
        or manifest["base_version"] != version
    ):
        raise ValueError("session tools internal manifest identity differs")
    tool_count = len(manifest["tools"])
    file_count = sum(
        len(tool["files"])
        for tool in manifest["tools"]
        if isinstance(tool, dict)
    )
    if asset["tool_count"] != tool_count or asset["file_count"] != file_count:
        raise ValueError("session tools asset counts differ")
    if (
        package_manifest.get("target") != "codex"
        or package_manifest.get("version") != version
    ):
        raise ValueError("session tools package identity differs")
    baseline = package_manifest.get("session_tools_baseline")
    if not isinstance(baseline, dict):
        raise ValueError("session tools package baseline is missing")
    _require_exact_keys(
        baseline,
        {"manifest_path", "manifest_sha256", "tools", "retired_tool_ids"},
        "session tools package baseline",
    )
    if baseline["manifest_path"] != BASELINE_MANIFEST_PATH:
        raise ValueError("session tools baseline manifest path differs")
    baseline_sha256 = hashlib.sha256(baseline_manifest_bytes).hexdigest()
    if (
        baseline["manifest_sha256"] != asset["manifest_sha256"]
        or baseline["manifest_sha256"] != baseline_sha256
    ):
        raise ValueError("session tools baseline manifest SHA-256 differs")
    baseline_manifest = validate_session_tools_manifest(
        baseline_manifest_bytes,
        expected_release_tag=str(tag),
        expected_base_version=version,
    )
    if baseline_manifest != manifest or baseline["tools"] != manifest["tools"]:
        raise ValueError("session tools baseline tools differ")
    retired = baseline["retired_tool_ids"]
    if not isinstance(retired, list) or any(
        not isinstance(tool_id, str) or not _TOOL_ID.fullmatch(tool_id)
        for tool_id in retired
    ):
        raise ValueError("session tools retired tool ids are invalid")
    if retired != sorted(set(retired)):
        raise ValueError(
            "session tools retired tool ids are not unique and sorted"
        )
    return manifest
