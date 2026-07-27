from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_base.matched_ab import (  # noqa: E402
    GuardViolation,
    SUPPORTED_CLIENT,
    build_codex_command,
    build_feature_preflight_command,
    inspect_event,
    parse_feature_states,
    planned_runs,
    response_sha256,
    summarize_abort,
    summarize_results,
)


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _surface_digest(home: Path) -> str:
    selected: list[Path] = []
    for path in (
        home / ".codex" / "AGENTS.md",
        home / ".codex" / "agents",
        home / ".agents" / "skills",
    ):
        if path.is_file():
            selected.append(path)
        elif path.is_dir():
            selected.extend(
                candidate
                for candidate in path.rglob("*")
                if candidate.is_file()
            )
        else:
            raise RuntimeError(
                f"managed A/B surface is missing: {path.relative_to(home)}"
            )
    digest = hashlib.sha256()
    for path in sorted(selected):
        relative = path.relative_to(home).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _copy_legacy_surface(source_profile: Path, destination: Path) -> None:
    source_agents = source_profile / ".codex" / "agents"
    source_skills = source_profile / ".agents" / "skills"
    source_guidance = source_profile / ".codex" / "AGENTS.md"
    if (
        not source_guidance.is_file()
        or not source_agents.is_dir()
        or not source_skills.is_dir()
    ):
        raise RuntimeError("legacy managed surface is incomplete")
    source_items = [
        source_guidance,
        *source_agents.glob("*.toml"),
        *(path / "SKILL.md" for path in source_skills.iterdir()),
    ]
    for source in source_items:
        try:
            attributes = source.stat().st_file_attributes
        except (AttributeError, FileNotFoundError):
            attributes = 0
        if source.is_symlink() or attributes & 0x400:
            raise RuntimeError(
                f"legacy managed surface contains a reparse point: {source}"
            )
    destination_guidance = destination / ".codex" / "AGENTS.md"
    destination_guidance.parent.mkdir(parents=True)
    shutil.copy2(source_guidance, destination_guidance)
    destination_agents = destination / ".codex" / "agents"
    destination_agents.mkdir()
    for source in sorted(source_agents.glob("*.toml")):
        shutil.copy2(source, destination_agents / source.name)
    destination_skills = destination / ".agents" / "skills"
    destination_skills.mkdir(parents=True)
    for source_directory in sorted(source_skills.iterdir()):
        skill = source_directory / "SKILL.md"
        if not source_directory.is_dir() or not skill.is_file():
            continue
        destination_directory = destination_skills / source_directory.name
        destination_directory.mkdir()
        shutil.copy2(skill, destination_directory / "SKILL.md")
    if len(list((destination / ".codex" / "agents").glob("*.toml"))) != 16:
        raise RuntimeError("legacy snapshot does not contain 16 agents")
    if len(list((destination / ".agents" / "skills").glob("*/SKILL.md"))) != 45:
        raise RuntimeError("legacy snapshot does not contain 45 skills")


def _foundation_install(
    foundation: Path,
    package: Path,
    home: Path,
) -> None:
    powershell = shutil.which("pwsh")
    if not powershell:
        raise RuntimeError("PowerShell 7 is required for matched A/B setup")
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(foundation),
            "install",
            "-Home",
            str(home),
            "-ClientId",
            "codex-cli",
            "-ClientVersion",
            SUPPORTED_CLIENT,
            "-Package",
            str(package),
            "-Json",
        ],
        cwd=foundation.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "candidate Foundation install failed: "
            + (result.stderr.strip() or result.stdout.strip())
        )
    agents = list((home / ".codex" / "agents").glob("*.toml"))
    skills = list((home / ".agents" / "skills").glob("*/SKILL.md"))
    if len(agents) != 16 or len(skills) != 38:
        raise RuntimeError(
            "candidate discovery differs after install: "
            f"agents={len(agents)}, skills={len(skills)}"
        )


def _isolated_environment(home: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "CODEX_ACCESS_TOKEN",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "CODEX_HOME": str(home / ".codex"),
            "USERPROFILE": str(home),
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_STATE_HOME": str(home / ".local" / "state"),
            "NO_COLOR": "1",
        }
    )
    return environment


def _copy_auth_without_reading(auth_source: Path, home: Path) -> None:
    if not auth_source.is_file():
        raise RuntimeError("Codex auth source is missing")
    destination = home / ".codex" / "auth.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(auth_source, destination)


def _check_client(codex: str, environment: dict[str, str]) -> None:
    result = subprocess.run(
        [codex, "--version"],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=15,
    )
    expected = f"codex-cli {SUPPORTED_CLIENT}"
    if result.returncode != 0 or result.stdout.strip() != expected:
        raise RuntimeError(
            "Codex A/B requires exact client " + SUPPORTED_CLIENT
        )


def _check_feature_controls(
    codex: str,
    environment: dict[str, str],
) -> None:
    result = subprocess.run(
        build_feature_preflight_command(codex=codex),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise GuardViolation(
            "Codex rejected the fail-closed A/B configuration",
            code="feature_preflight",
        )
    parse_feature_states(result.stdout)


def _reader(
    stream: Any,
    destination: queue.Queue[str | None],
) -> None:
    try:
        for line in iter(stream.readline, ""):
            destination.put(line)
    finally:
        destination.put(None)


def _terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _run_one(
    *,
    codex: str,
    home: Path,
    workspace: Path,
    prompt: str,
    timeout_seconds: int,
) -> tuple[dict[str, int], str]:
    command = build_codex_command(
        codex=codex,
        workspace=workspace,
        prompt=prompt,
    )
    output_queue: queue.Queue[str | None] = queue.Queue()
    error_queue: queue.Queue[str | None] = queue.Queue()
    process = subprocess.Popen(
        command,
        cwd=workspace,
        env=_isolated_environment(home),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    assert process.stderr is not None
    output_thread = threading.Thread(
        target=_reader,
        args=(process.stdout, output_queue),
        daemon=True,
    )
    error_thread = threading.Thread(
        target=_reader,
        args=(process.stderr, error_queue),
        daemon=True,
    )
    output_thread.start()
    error_thread.start()
    deadline = time.monotonic() + timeout_seconds
    usage: dict[str, int] | None = None
    final_message: str | None = None
    output_finished = False
    try:
        while not output_finished:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GuardViolation(
                    "Codex A/B call timed out",
                    code="timeout",
                )
            try:
                line = output_queue.get(timeout=min(0.25, remaining))
            except queue.Empty:
                if process.poll() is not None and not output_thread.is_alive():
                    break
                continue
            if line is None:
                output_finished = True
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise GuardViolation(
                    "Codex emitted non-JSON output in --json mode",
                    code="invalid_event",
                ) from error
            observation = inspect_event(event)
            if "usage" in observation:
                usage = observation["usage"]
            if "message" in observation:
                final_message = observation["message"]
    except BaseException:
        _terminate(process)
        raise
    try:
        process.wait(timeout=max(1, int(deadline - time.monotonic())))
    except subprocess.TimeoutExpired as error:
        _terminate(process)
        raise GuardViolation(
            "Codex A/B process did not exit after the event stream ended",
            code="timeout",
        ) from error
    error_thread.join(timeout=2)
    errors: list[str] = []
    while True:
        try:
            line = error_queue.get_nowait()
        except queue.Empty:
            break
        if line is not None:
            errors.append(line)
    if process.returncode != 0:
        raise GuardViolation(
            "Codex A/B call failed without usable evidence: "
            + "".join(errors)[-2000:],
            code="call_failed",
        )
    if usage is None or final_message is None:
        raise GuardViolation(
            "Codex A/B call completed without usage or final message",
            code="invalid_event",
        )
    return usage, response_sha256(final_message)


def _atomic_write_new(path: Path, value: Any) -> None:
    if path.exists():
        raise RuntimeError(
            "matched A/B evidence already exists; repeat requires new approval"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise RuntimeError("matched A/B temporary evidence already exists")
    temporary.write_bytes(_json_bytes(value))
    os.replace(temporary, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the owner-approved four-call Codex matched A/B matrix. "
            "Without --execute-approved-four this command is a dry-run."
        )
    )
    parser.add_argument("--execute-approved-four", action="store_true")
    parser.add_argument("--codex", default=shutil.which("codex") or "codex")
    parser.add_argument("--foundation", type=Path)
    parser.add_argument("--candidate-package", type=Path)
    parser.add_argument("--legacy-profile", type=Path, default=Path.home())
    parser.add_argument(
        "--auth-file",
        type=Path,
        default=Path.home() / ".codex" / "auth.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/matched-ab-evidence.json"),
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    plan = {
        "schema_version": 1,
        "would_execute": bool(args.execute_approved_four),
        "calls": [
            {
                "ordinal": index,
                "variant": run.variant,
                "prompt_id": run.prompt_id,
                "prompt_sha256": hashlib.sha256(
                    run.prompt.encode("utf-8")
                ).hexdigest(),
            }
            for index, run in enumerate(planned_runs(), start=1)
        ],
        "calls_total": 4,
        "client_version": SUPPORTED_CLIENT,
        "model": "gpt-5.6-terra",
        "reasoning_effort": "low",
        "tools": "disabled-and-fail-closed",
        "input_token_abort_threshold": 100_000,
    }
    if not args.execute_approved_four:
        print(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    if args.foundation is None or args.candidate_package is None:
        raise SystemExit(
            "--foundation and --candidate-package are required for execution"
        )
    foundation = args.foundation.resolve()
    package = args.candidate_package.resolve()
    if not foundation.is_file() or not package.is_file():
        raise SystemExit("Foundation or candidate package does not exist")
    if args.timeout_seconds < 30 or args.timeout_seconds > 600:
        raise SystemExit("--timeout-seconds must be between 30 and 600")

    with tempfile.TemporaryDirectory(prefix="codex-matched-ab-") as raw_work:
        work = Path(raw_work)
        legacy_home = work / "home-a"
        candidate_home = work / "home-b"
        workspace = work / "empty-workspace"
        legacy_home.mkdir()
        candidate_home.mkdir()
        workspace.mkdir()
        auth_paths = [
            legacy_home / ".codex" / "auth.json",
            candidate_home / ".codex" / "auth.json",
        ]
        try:
            _copy_legacy_surface(args.legacy_profile.resolve(), legacy_home)
            _foundation_install(foundation, package, candidate_home)
            _copy_auth_without_reading(
                args.auth_file.resolve(),
                legacy_home,
            )
            _copy_auth_without_reading(
                args.auth_file.resolve(),
                candidate_home,
            )
            _check_client(args.codex, _isolated_environment(legacy_home))
            _check_client(args.codex, _isolated_environment(candidate_home))
            _check_feature_controls(
                args.codex,
                _isolated_environment(legacy_home),
            )
            _check_feature_controls(
                args.codex,
                _isolated_environment(candidate_home),
            )
            surface_hashes = {
                "legacy": _surface_digest(legacy_home),
                "candidate": _surface_digest(candidate_home),
            }
            package_sha256 = hashlib.sha256(package.read_bytes()).hexdigest()
            package_bytes = package.stat().st_size

            results: list[dict[str, Any]] = []
            calls_started = 0
            try:
                for run in planned_runs():
                    calls_started += 1
                    home = (
                        legacy_home
                        if run.variant == "legacy"
                        else candidate_home
                    )
                    usage, result_digest = _run_one(
                        codex=args.codex,
                        home=home,
                        workspace=workspace,
                        prompt=run.prompt,
                        timeout_seconds=args.timeout_seconds,
                    )
                    results.append(
                        {
                            "variant": run.variant,
                            "prompt_id": run.prompt_id,
                            "usage": usage,
                            "result_sha256": result_digest,
                        }
                    )
            except GuardViolation as error:
                evidence = summarize_abort(
                    client_version=SUPPORTED_CLIENT,
                    failure_code=error.code,
                    calls_started=calls_started,
                    completed_results=results,
                    legacy_surface_sha256=surface_hashes["legacy"],
                    candidate_surface_sha256=surface_hashes["candidate"],
                    candidate_package_sha256=package_sha256,
                    candidate_package_bytes=package_bytes,
                )
                _atomic_write_new(args.output.resolve(), evidence)
                print(
                    json.dumps(
                        evidence,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                return 2

            evidence = summarize_results(
                results,
                client_version=SUPPORTED_CLIENT,
                legacy_surface_sha256=surface_hashes["legacy"],
                candidate_surface_sha256=surface_hashes["candidate"],
                candidate_package_sha256=package_sha256,
                candidate_package_bytes=package_bytes,
            )
            _atomic_write_new(args.output.resolve(), evidence)
            print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
        finally:
            for auth_path in auth_paths:
                try:
                    auth_path.unlink(missing_ok=True)
                except OSError as error:
                    raise RuntimeError(
                        "temporary Codex auth copy could not be removed"
                    ) from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
