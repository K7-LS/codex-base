from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from pathlib import Path


def _skill_metadata(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        raise ValueError(f"missing skill frontmatter: {path}")
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values["name"], values["description"]


def _surface(payload: bytes, **extra: object) -> dict[str, object]:
    return {
        **extra,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _candidate_surfaces(repo_root: Path) -> dict[str, dict[str, object]]:
    hot = (repo_root / "AGENTS.md").read_bytes()

    skill_paths = [
        *sorted((repo_root / "skills").glob("*/SKILL.md")),
        *sorted((repo_root / "control-skills").glob("*/SKILL.md")),
    ]
    skill_rows = []
    for path in skill_paths:
        name, description = _skill_metadata(path)
        skill_rows.append(
            f"{name}|{description}|.agents/skills/{path.parent.name}/SKILL.md"
        )
    skills = "\n".join(skill_rows).encode("utf-8")

    agent_paths = sorted((repo_root / "agents").glob("*.toml"))
    agent_rows = []
    for path in agent_paths:
        metadata = tomllib.loads(path.read_text(encoding="utf-8"))
        agent_rows.append(
            f"{metadata['name']}|{metadata['description']}|"
            f".codex/agents/{path.name}"
        )
    agents = "\n".join(agent_rows).encode("utf-8")
    return {
        "hot": _surface(hot, logical_path="~/.codex/AGENTS.md"),
        "skills_discovery": _surface(
            skills,
            logical_root="~/.agents/skills",
            count=len(skill_paths),
            capability_skills=37,
            control_skills=1,
        ),
        "agents_discovery": _surface(
            agents,
            logical_root="~/.codex/agents",
            count=len(agent_paths),
        ),
    }


def audit_static_context(
    repo_root: Path,
    baseline_path: Path | None = None,
) -> dict[str, object]:
    baseline_path = baseline_path or (
        repo_root / "baselines" / "legacy-hub-2026-07-26.json"
    )
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = _candidate_surfaces(repo_root)
    candidate_bytes = sum(int(value["bytes"]) for value in candidate.values())
    legacy_bytes = int(baseline["total_bytes"])
    reduction = 1.0 - (candidate_bytes / legacy_bytes)
    static_pass = reduction >= 0.70
    return {
        "schema_version": 1,
        "method": baseline["method"],
        "legacy": baseline,
        "candidate": {
            "surfaces": candidate,
            "total_bytes": candidate_bytes,
            "estimated_tokens": math.ceil(candidate_bytes / 3),
            "cold_payload_in_startup": False,
        },
        "thresholds": {
            "base_controlled_startup_reduction_min": 0.70,
            "matched_ab_total_input_reduction_min": 0.25,
        },
        "results": {
            "base_controlled_startup_reduction": reduction,
            "STATIC_TOKEN_ACCEPTANCE": "PASS" if static_pass else "NOT_PASS",
            "MATCHED_AB": "NOT_RUN",
        },
        "limitations": [
            "Static tokens are a conservative UTF-8 byte estimate, not provider billing.",
            "Matched A/B requires separate owner approval and identical client, model, reasoning and prompts.",
        ],
    }
