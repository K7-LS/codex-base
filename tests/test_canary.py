from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from codex_base.acceptance import evidence_body_sha256
from codex_base.canary import build_canary_evidence, surface_digest


def test_surface_digest_ignores_foundation_state_but_binds_user_surface(
    tmp_path: Path,
):
    home = tmp_path / "home"
    user_file = home / ".codex" / "AGENTS.md"
    state_file = home / ".llm-foundation" / "state" / "codex" / "state.json"
    user_file.parent.mkdir(parents=True)
    state_file.parent.mkdir(parents=True)
    user_file.write_text("before", encoding="utf-8")
    state_file.write_text("state-one", encoding="utf-8")
    first = surface_digest(home)

    state_file.write_text("state-two", encoding="utf-8")
    assert surface_digest(home) == first

    user_file.write_text("changed", encoding="utf-8")
    assert surface_digest(home) != first


def test_canary_evidence_requires_exact_rollback_and_discovery():
    binding = {
        "target": "codex",
        "version": "0.1.1",
        "asset": {
            "name": "codex-base-0.1.1.zip",
            "sha256": "a" * 64,
            "bytes": 123,
        },
    }
    evidence = build_canary_evidence(
        release_binding=binding,
        client_version="0.146.0-alpha.3.1",
        foundation_sha256="b" * 64,
        before_surface_sha256="c" * 64,
        after_rollback_surface_sha256="c" * 64,
        phase_statuses={
            "plan": "READY",
            "install": "CANONICAL_WITH_LOCAL_EXCEPTIONS",
            "doctor": "CANONICAL_WITH_LOCAL_EXCEPTIONS",
            "inventory": "INVENTORIED",
            "rollback": "ROLLED_BACK",
        },
        discovery={"agents": 16, "skills": 41},
        preserved_files=8,
    )

    assert evidence["CODEX_CANARY"] == "PASS"
    assert evidence["model_requests"] == 0
    assert evidence["rollback"]["byte_identical"] is True
    assert (
        evidence["evidence_body_sha256"]
        == evidence_body_sha256(evidence)
    )


@pytest.mark.parametrize(
    ("after", "agents", "skills"),
    [
        ("d" * 64, 16, 39),
        ("c" * 64, 15, 39),
        ("c" * 64, 16, 40),
    ],
)
def test_canary_evidence_fails_closed_on_rollback_or_discovery(
    after: str,
    agents: int,
    skills: int,
):
    with pytest.raises(ValueError, match="canary"):
        build_canary_evidence(
            release_binding={
                "target": "codex",
                "version": "0.1.1",
                "asset": {
                    "name": "codex-base-0.1.1.zip",
                    "sha256": hashlib.sha256(b"package").hexdigest(),
                    "bytes": 7,
                },
            },
            client_version="0.146.0-alpha.3.1",
            foundation_sha256="b" * 64,
            before_surface_sha256="c" * 64,
            after_rollback_surface_sha256=after,
            phase_statuses={
                "plan": "READY",
                "install": "CANONICAL_WITH_LOCAL_EXCEPTIONS",
                "doctor": "CANONICAL_WITH_LOCAL_EXCEPTIONS",
                "inventory": "INVENTORIED",
                "rollback": "ROLLED_BACK",
            },
            discovery={"agents": agents, "skills": skills},
            preserved_files=8,
        )
