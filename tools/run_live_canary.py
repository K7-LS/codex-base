from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_base.canary import build_canary_evidence, surface_digest  # noqa: E402
from codex_base.promotion import _verify_candidate  # noqa: E402


SUPPORTED_CLIENT = "0.146.0-alpha.3.1"


def _run_json(command: list[str], environment: dict[str, str]) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=240,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout)[-3000:]
        raise RuntimeError(f"canary command failed: {detail}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("canary command did not return JSON") from error
    if not isinstance(value, dict):
        raise RuntimeError("canary command returned a non-object")
    return value


def _foundation_command(
    *,
    powershell: str,
    foundation: Path,
    action: str,
    home: Path,
    package: Path | None = None,
    target: str | None = None,
) -> list[str]:
    command = [
        powershell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(foundation),
        action,
        "-Home",
        str(home),
        "-Json",
        "-ClientId",
        "codex-cli",
        "-ClientVersion",
        SUPPORTED_CLIENT,
    ]
    if package is not None:
        command.extend(["-Package", str(package)])
    if target is not None:
        command.extend(["-Target", target])
    return command


def _seed_isolated_home(home: Path) -> dict[Path, bytes]:
    sentinels = {
        home / ".codex" / "auth.json": b'{"canary":"preserve"}\n',
        home / ".codex" / "sessions" / "one.json": b"session\n",
        home / ".codex" / "archived_sessions" / "old.json": b"archive\n",
        home / ".codex" / "memories" / "memory.md": b"memory\n",
        home / ".codex" / "state.sqlite": b"sqlite\n",
        home / ".codex" / "browser" / "state.json": b"browser\n",
        home / ".agents" / "skills" / "local-canary" / "SKILL.md": (
            b"# local canary skill\n"
        ),
        home / "project" / "work.txt": b"project\n",
    }
    for path, payload in sentinels.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    guidance = home / ".codex" / "AGENTS.md"
    guidance.write_text("# pre-canary managed surface\n", encoding="utf-8")
    return sentinels


def _write_new(path: Path, value: object) -> None:
    if path.exists():
        raise RuntimeError("canary evidence exists; refusing to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run one no-model Codex package canary in an isolated fake home: "
            "plan, install, doctor, inventory, rollback."
        )
    )
    parser.add_argument("--candidate-dir", required=True, type=Path)
    parser.add_argument("--foundation", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--codex", default=shutil.which("codex") or "codex")
    parser.add_argument("--powershell", default=shutil.which("pwsh") or "pwsh")
    arguments = parser.parse_args()

    candidate_dir = arguments.candidate_dir.resolve()
    foundation = arguments.foundation.resolve()
    if not foundation.is_file():
        raise SystemExit("Foundation script is missing")
    _, binding, package, _, _ = _verify_candidate(candidate_dir)
    client = subprocess.run(
        [arguments.codex, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=15,
    )
    if (
        client.returncode != 0
        or client.stdout.strip() != f"codex-cli {SUPPORTED_CLIENT}"
    ):
        raise SystemExit(f"Codex client must be exactly {SUPPORTED_CLIENT}")

    with tempfile.TemporaryDirectory(prefix="codex-live-canary-") as raw:
        work = Path(raw)
        home = work / "isolated-home"
        home.mkdir()
        sentinels = _seed_isolated_home(home)
        before = surface_digest(home)
        environment = os.environ.copy()
        environment["FOUNDATION_ACCEPTANCE_MODE"] = "1"
        environment["TEMP"] = str(work / "temp")
        environment["TMP"] = str(work / "temp")
        (work / "temp").mkdir()

        plan = _run_json(
            _foundation_command(
                powershell=arguments.powershell,
                foundation=foundation,
                action="plan",
                home=home,
                package=package,
            ),
            environment,
        )
        install = _run_json(
            _foundation_command(
                powershell=arguments.powershell,
                foundation=foundation,
                action="install",
                home=home,
                package=package,
            ),
            environment,
        )
        discovery = {
            "agents": len(list((home / ".codex" / "agents").glob("*.toml"))),
            "skills": len(
                list((home / ".agents" / "skills").glob("*/SKILL.md"))
            ),
        }
        doctor = _run_json(
            _foundation_command(
                powershell=arguments.powershell,
                foundation=foundation,
                action="doctor",
                home=home,
                package=package,
            ),
            environment,
        )
        inventory = _run_json(
            _foundation_command(
                powershell=arguments.powershell,
                foundation=foundation,
                action="inventory",
                home=home,
                target="codex",
            ),
            environment,
        )
        rollback = _run_json(
            _foundation_command(
                powershell=arguments.powershell,
                foundation=foundation,
                action="rollback",
                home=home,
                target="codex",
            ),
            environment,
        )
        for path, payload in sentinels.items():
            if path.read_bytes() != payload:
                raise RuntimeError(f"preserved file changed: {path.name}")
        after = surface_digest(home)
        evidence = build_canary_evidence(
            release_binding=binding,
            client_version=SUPPORTED_CLIENT,
            foundation_sha256=hashlib.sha256(
                foundation.read_bytes()
            ).hexdigest(),
            before_surface_sha256=before,
            after_rollback_surface_sha256=after,
            phase_statuses={
                "plan": str(plan.get("status")),
                "install": str(install.get("status")),
                "doctor": str(doctor.get("status")),
                "inventory": (
                    "INVENTORIED"
                    if inventory.get("status") == "INSTALLED"
                    else str(inventory.get("status"))
                ),
                "rollback": str(rollback.get("status")),
            },
            discovery=discovery,
            preserved_files=len(sentinels),
        )
    _write_new(arguments.output.resolve(), evidence)
    print(
        json.dumps(
            {
                "CODEX_CANARY": evidence["CODEX_CANARY"],
                "output": str(arguments.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
