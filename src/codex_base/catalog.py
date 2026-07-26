from __future__ import annotations

import json
from pathlib import Path


def load_catalog(repo_root: Path) -> dict[str, list[dict[str, str]]]:
    catalog_root = repo_root / "catalog"
    return {
        "agents": json.loads((catalog_root / "agents.json").read_text(encoding="utf-8")),
        "skills": json.loads((catalog_root / "skills.json").read_text(encoding="utf-8")),
    }


def estimate_discovery_payload(
    catalog: dict[str, list[dict[str, object]]], home: Path
) -> dict[str, int]:
    skill_rows = []
    for item in catalog["skills"]:
        path = home / ".agents" / str(item["source"])
        skill_rows.append(f"{item['name']}\n{item['description']}\n{path}")
    agent_rows = [
        f"{item['name']}\n{item['description']}" for item in catalog["agents"]
    ]
    return {
        "skill_chars": len("\n".join(skill_rows)),
        "agent_chars": len("\n".join(agent_rows)),
    }
