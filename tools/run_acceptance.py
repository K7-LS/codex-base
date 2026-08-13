from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_base.acceptance import write_acceptance_evidence
from codex_base.release import (
    SUPPORTED_CODEX_CLIENT,
    assert_clean_git_source,
    bind_acceptance_evidence,
    build_release,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_dist_path(root: Path, version: str) -> Path:
    if re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)",
        version,
    ) is None:
        raise ValueError("Version must use canonical X.Y.Z format")
    dist_root = (root / "dist").resolve()
    candidate = (dist_root / f"candidate-{version}").resolve()
    if candidate.parent != dist_root:
        raise ValueError("Candidate path must be a direct child of dist")
    return candidate


def _run(command: list[str], cwd: Path, env: dict[str, str] | None = None):
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _foundation_command(
    executable: str,
    foundation: Path,
    command: str,
    home: Path,
    package: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    arguments = [
        executable,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(foundation),
        command,
        "-Home",
        str(home),
        "-ClientId",
        "codex-cli",
        "-ClientVersion",
        SUPPORTED_CODEX_CLIENT,
        "-Json",
    ]
    if package is not None:
        arguments.extend(["-Package", str(package)])
        if command in {"plan", "install"}:
            arguments.append("-ConfirmRemoveUnknown")
    else:
        arguments.extend(["-Target", "codex"])
    return _run(arguments, cwd=foundation.parent)


def _seed(home: Path) -> dict[str, str]:
    payloads = {
        ".codex/auth.json": b'{"token":"preserve"}\n',
        ".codex/sessions/session.json": b"session\n",
        ".codex/archived_sessions/archive.json": b"archive\n",
        ".codex/memories/memory.md": b"memory\n",
        ".codex/state.sqlite": b"sqlite\n",
        ".codex/browser/state.json": b"browser\n",
        ".codex/agents/legacy.toml": b'name = "legacy"\n',
        ".agents/skills/local-personal/SKILL.md": b"# local skill\n",
        "project/work.txt": b"project\n",
    }
    for relative, payload in payloads.items():
        path = home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    previous = home / ".codex" / "AGENTS.md"
    previous.write_text("# previous managed surface\n", encoding="utf-8")
    return {
        relative: _sha256(home / relative)
        for relative in payloads
    }


def _assert_preserved(home: Path, sentinels: dict[str, str]) -> None:
    for relative, digest in sentinels.items():
        path = home / relative
        if not path.is_file() or _sha256(path) != digest:
            raise AssertionError(f"preserved path changed: {relative}")


def _integration_case(
    executable: str,
    foundation: Path,
    package: Path,
    root: Path,
) -> dict[str, object]:
    home = root / Path(executable).stem
    home.mkdir(parents=True)
    sentinels = _seed(home)
    before = _files(home)

    plan = _foundation_command(
        executable, foundation, "plan", home, package
    )
    if plan.returncode != 0:
        raise AssertionError(plan.stdout or plan.stderr)
    if _files(home) != before:
        raise AssertionError("plan mutated target home")

    install = _foundation_command(
        executable, foundation, "install", home, package
    )
    if install.returncode != 0:
        raise AssertionError(install.stdout or install.stderr)
    _assert_preserved(home, sentinels)
    if (home / ".claude").exists():
        raise AssertionError("Codex install created a Claude runtime path")
    agent_files = sorted((home / ".codex" / "agents").glob("*.toml"))
    skill_files = sorted((home / ".agents" / "skills").glob("*/SKILL.md"))
    if len(agent_files) != 17 or len(skill_files) != 39:
        raise AssertionError(
            f"installed discovery differs: agents={len(agent_files)} "
            f"skills={len(skill_files)}"
        )
    doctor = _foundation_command(
        executable, foundation, "doctor", home, package
    )
    if doctor.returncode != 0:
        raise AssertionError(doctor.stdout or doctor.stderr)
    inventory = _foundation_command(
        executable, foundation, "inventory", home
    )
    if inventory.returncode != 0:
        raise AssertionError(inventory.stdout or inventory.stderr)
    inventory_data = json.loads(inventory.stdout)
    if inventory_data.get("quarantined_unknown") != []:
        raise AssertionError("unknown discovery inventory differs")

    rollback = _foundation_command(
        executable, foundation, "rollback", home
    )
    if rollback.returncode != 0:
        raise AssertionError(rollback.stdout or rollback.stderr)
    _assert_preserved(home, sentinels)
    if (
        home / ".codex" / "AGENTS.md"
    ).read_text(encoding="utf-8") != "# previous managed surface\n":
        raise AssertionError("previous AGENTS.md was not restored")
    if not (
        home / ".agents" / "skills" / "local-personal" / "SKILL.md"
    ).is_file():
        raise AssertionError("unknown skill was not restored")
    legacy_agent = home / ".codex" / "agents" / "legacy.toml"
    if (
        not legacy_agent.is_file()
        or legacy_agent.read_text(encoding="utf-8") != 'name = "legacy"\n'
    ):
        raise AssertionError("unknown agent was not restored")
    if any(
        path.is_file()
        for path in (
            home / ".agents" / "skills" / "sync-base"
        ).rglob("*")
    ):
        raise AssertionError("candidate discovery remained after rollback")
    return {
        "status": "PASS",
        "executable": executable,
        "agents": 16,
        "capability_skills": 37,
        "control_skills": 1,
        "preserved_sentinels": len(sentinels),
        "unknown_discovery_preserved": True,
        "total_discovery": {"agents": 17, "skills": 39},
        "rollback_restored_previous_surface": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="0.1.1")
    parser.add_argument("--foundation", required=True, type=Path)
    parser.add_argument("--foundation-evidence", required=True, type=Path)
    args = parser.parse_args(argv)

    root = ROOT
    dist = _candidate_dist_path(root, args.version)
    source = assert_clean_git_source(root)
    work = root / ".work" / "acceptance"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    foundation = args.foundation.resolve()
    foundation_evidence = json.loads(
        args.foundation_evidence.resolve().read_text(encoding="utf-8")
    )
    if foundation_evidence.get("FOUNDATION_SYNTHETIC") != "PASS":
        raise SystemExit("Foundation evidence is not PASS")
    foundation_files = _files(foundation)
    required_foundation = {
        "VERSION",
        "engine-manifest.json",
        "foundation.ps1",
    }
    if not required_foundation.issubset(foundation_files):
        raise SystemExit("Foundation engine inventory is incomplete")
    accepted_builds = foundation_evidence.get("engine_builds")
    if not isinstance(accepted_builds, dict) or any(
        not isinstance(accepted_builds.get(shell), dict)
        or accepted_builds[shell].get("status") != "PASS"
        or accepted_builds[shell].get("files") != foundation_files
        for shell in ("ps7", "ps51")
    ):
        raise SystemExit("Foundation engine bytes differ from acceptance")

    first = build_release(root, work / "build-one", args.version, foundation)
    second = build_release(root, work / "build-two", args.version, foundation)
    deterministic = (
        _sha256(first.zip_path) == _sha256(second.zip_path)
        and first.manifest_path.read_bytes() == second.manifest_path.read_bytes()
        and first.component_lock_path.read_bytes()
        == second.component_lock_path.read_bytes()
    )

    pytest_result = _run(
        [sys.executable, "-m", "pytest", "-q"],
        root,
    )
    tests = {
        "status": "PASS" if pytest_result.returncode == 0 else "NOT_PASS",
        "returncode": pytest_result.returncode,
        "stdout": pytest_result.stdout,
        "stderr": pytest_result.stderr,
    }

    cases = []
    errors = []
    for executable in (
        shutil.which("pwsh"),
        shutil.which("powershell.exe"),
    ):
        if not executable:
            errors.append("required PowerShell executable is missing")
            continue
        try:
            cases.append(
                _integration_case(
                    executable,
                    foundation / "foundation.ps1",
                    first.zip_path,
                    work / "fake-homes",
                )
            )
        except (AssertionError, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{executable}: {exc}")

    integration_pass = (
        deterministic
        and tests["status"] == "PASS"
        and len(cases) == 2
        and not errors
    )
    integration = {
        "status": "PASS" if integration_pass else "NOT_PASS",
        "deterministic_candidate_zip": deterministic,
        "candidate_zip_sha256": _sha256(first.zip_path),
        "cases": cases,
        "errors": errors,
        "scope": "real 16-agent/37-capability-skill candidate in isolated fake homes",
    }

    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)
    for path in (
        first.zip_path,
        first.component_lock_path,
    ):
        shutil.copy2(path, dist / path.name)
    evidence = write_acceptance_evidence(
        repo_root=root,
        destination=dist / "acceptance-evidence.json",
        version=args.version,
        foundation_evidence=foundation_evidence,
        release_manifest=first.manifest,
        offline_integration=integration,
        test_evidence=tests,
    )
    shutil.copy2(first.manifest_path, dist / first.manifest_path.name)
    bound_manifest = bind_acceptance_evidence(
        dist / first.manifest_path.name,
        dist / "acceptance-evidence.json",
    )
    summary = {
        "source": source,
        "candidate_dir": dist.relative_to(root).as_posix(),
        "candidate_zip_sha256": integration["candidate_zip_sha256"],
        "components_lock_sha256": bound_manifest[
            "components_lock_sha256"
        ],
        "acceptance_evidence_sha256": bound_manifest[
            "acceptance_evidence_sha256"
        ],
        "FOUNDATION_SYNTHETIC": evidence["FOUNDATION_SYNTHETIC"],
        "CANDIDATE_OFFLINE": evidence["CANDIDATE_OFFLINE"],
        "MATCHED_AB": evidence["MATCHED_AB"],
        "CODEX_CANARY": evidence["CODEX_CANARY"],
        "FULL_RELEASE_CODEX": evidence["FULL_RELEASE_CODEX"],
        "PROGRAM_RELEASE": evidence["PROGRAM_RELEASE"],
    }
    (dist / "offline-acceptance-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if evidence["CANDIDATE_OFFLINE"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
