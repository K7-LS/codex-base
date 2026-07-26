from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest


def _load_acceptance_tool(repo_root: Path):
    path = repo_root / "tools" / "run_acceptance.py"
    spec = importlib.util.spec_from_file_location("run_acceptance_tool", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "version",
    (
        "",
        "1.2",
        "1.2.3-beta",
        "01.2.3",
        "../victim",
        "x/../../victim",
        r"x\..\..\victim",
    ),
)
def test_acceptance_candidate_path_rejects_unsafe_version(
    repo_root: Path, version: str
):
    tool = _load_acceptance_tool(repo_root)
    with pytest.raises(ValueError, match="X.Y.Z"):
        tool._candidate_dist_path(repo_root, version)


def test_acceptance_candidate_path_is_direct_dist_child(repo_root: Path):
    tool = _load_acceptance_tool(repo_root)
    expected = (repo_root / "dist" / "candidate-12.34.56").resolve()
    assert tool._candidate_dist_path(repo_root, "12.34.56") == expected
    assert expected.parent == (repo_root / "dist").resolve()


def test_public_osint_skill_has_no_personal_runtime_contract(repo_root: Path):
    skill_root = repo_root / "skills" / "local-osint-recon"
    payload = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(skill_root.rglob("*"))
        if path.is_file()
    )
    forbidden = (
        "в Codex-base не переносить",
        "ЛИЧНЫЙ",
        "osint-arsenal-revizia",
        "DANIIL-LAPTOP",
        "C:\\Users\\Даниил",
    )
    for marker in forbidden:
        assert marker not in payload
    assert not re.search(r"(?i)C:\\Users\\[^\\\r\n]+\\", payload)
    assert "LOCAL_OSINT_WSL_DISTRO" in payload
    assert "не устанавливает" in payload


def test_installable_payload_has_no_personal_machine_example(repo_root: Path):
    for root_name in ("agents", "skills", "cold"):
        for path in (repo_root / root_name).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {
                ".md",
                ".py",
                ".toml",
            }:
                continue
            text = path.read_text(encoding="utf-8")
            assert "DANIIL-LAPTOP" not in text
            assert "C:\\Users\\Даниил" not in text
            assert "C:/Users/Даниил" not in text
