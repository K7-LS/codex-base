"""Explicitly upgrade a known Hindsight bridge in an already opted-in project."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid


FILES = (Path("hooks.json"), Path("hooks/hindsight-bridge.ps1"))
KNOWN_PAIRS = {
    # Published 0.2.5 and the verified local hotfix preceding 0.2.6.
    ("daf6f7991784bb49c74c40f814f099809e5ef24cbbeb49be2741ba1d7efaa392",
     "fd2f2d261cbc22f62b611cfe2a90c1312c986bb4dcdc3b3962f38276e9e62cdd"),
    ("dd88e53a49caaee6f4fe8708266a62027d964dc5162f96f3827e44a985e0e455",
     "2844b6f815fa8133d1e2e0b65a6977dbad03f1e241b30dcf9dc889941ba6b42f"),
}
EVENT_SCRIPTS = ("codex-sessionstart-hook.js", "codex-hook.js", "codex-stop-hook.js")
TARGET_PAIR = ("0c930e22dcb56eed60ae215663ce141ed01e92dd3fb06b76b4bd0c1e70807060",
               "546ce75c7755864cb75b3ada5b1ea55bc7a45f5bc71bf51baeba68e903240e1a")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _write(path, data):
    temporary = path.with_name(path.name + ".upgrade-" + uuid.uuid4().hex)
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def upgrade(home, project, apply=False):
    home, project = Path(home).resolve(), Path(project).resolve()
    settings_path = home / ".hindsight" / "coding-agent.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        if not isinstance(settings, dict):
            return {"status": "BLOCKED", "reason": "Hindsight settings must be a JSON object"}
        mapping = settings.get("mapPathToBank", {})
        selected = isinstance(mapping, dict) and any(
            isinstance(key, str) and isinstance(bank, str) and bool(bank.strip())
            and os.path.normcase(str(Path(key).resolve())) == os.path.normcase(str(project))
            for key, bank in mapping.items()
        )
    except (OSError, ValueError, TypeError):
        return {"status": "BLOCKED", "reason": "Hindsight settings are missing or invalid"}
    if settings.get("optInOnly") is not True or not selected:
        return {"status": "BLOCKED", "reason": "Project is not explicitly opted in with optInOnly"}
    scripts = home / ".hindsight" / "coding-agents" / "dist"
    if not all((scripts / name).is_file() for name in EVENT_SCRIPTS):
        return {"status": "BLOCKED", "reason": "Installed Hindsight event scripts are incomplete"}

    source = home / ".agents" / "skills" / "llm-interop" / "assets" / "hindsight-project-hooks"
    destination = project / ".codex"
    if not all((root / name).is_file() and not (root / name).is_symlink()
               for root in (source, destination) for name in FILES):
        return {"status": "BLOCKED", "reason": "Both installed templates and an existing project bridge are required"}
    originals = [(destination / name).read_bytes() for name in FILES]
    replacements = [(source / name).read_bytes() for name in FILES]
    before, after = tuple(map(digest, originals)), tuple(map(digest, replacements))
    if after != TARGET_PAIR:
        return {"status": "BLOCKED", "reason": "Installed Hindsight templates differ from the verified upgrade target"}
    if before == after:
        return {"status": "CURRENT", "changed_files": []}
    if before not in KNOWN_PAIRS:
        return {"status": "NEEDS_REVIEW", "reason": "Custom or unknown project hooks were preserved"}
    report = {"status": "READY", "changed_files": [str(name) for name in FILES],
              "before_sha256": list(before), "after_sha256": list(after)}
    if not apply:
        return report

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = destination / "backups" / ("hindsight-upgrade-" + stamp + "-" + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True, exist_ok=False)
    for name, data in zip(FILES, originals):
        path = backup / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if path.read_bytes() != data:
            raise OSError("Project backup verification failed; no bridge files changed")
    report["backup"] = str(backup)
    (backup / "receipt.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        for name, data in zip(FILES, replacements):
            _write(destination / name, data)
        if tuple(digest((destination / name).read_bytes()) for name in FILES) != after:
            raise OSError("Project bridge verification failed")
    except OSError:
        try:
            for name, data in zip(FILES, originals):
                _write(destination / name, data)
            if [(destination / name).read_bytes() for name in FILES] != originals:
                raise OSError("Project rollback verification failed")
        except OSError:
            report["status"] = "ROLLBACK_FAILED"
            report["next"] = "Restore both project files from the recorded backup before retrying"
            return report
        report["status"] = "ROLLED_BACK"
        return report
    report["status"] = "UPDATED"
    report["next"] = "Trust changed project hooks and verify them in a new Codex session"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        report = upgrade(args.home, args.project, apply=args.apply)
    except (OSError, ValueError):
        report = {"status": "BLOCKED", "reason": "File operation failed; inspect the project backup before retrying"}
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] in {"READY", "CURRENT", "UPDATED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
