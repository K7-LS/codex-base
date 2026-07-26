from __future__ import annotations

from pathlib import Path

from codex_base.catalog import estimate_discovery_payload, load_catalog


EXPECTED_AGENT_IDS = {
    "audit-rd-section",
    "auditor",
    "designer",
    "excel-validator",
    "expertiza-responder",
    "id-engineer",
    "kp-writer",
    "letter-writer",
    "norm-lookup",
    "pdf-reviewer",
    "pto-engineer",
    "pyrevit-engineer",
    "rd-coordinator",
    "smetchik",
    "snabzhenets",
    "word-checker",
}

EXPECTED_SKILL_IDS = {
    "acad-recreation",
    "cad-reader",
    "chains-pattern",
    "co-verify",
    "doc-extract",
    "doc-finder",
    "domain-grilling",
    "excel-helper",
    "facts-layer",
    "graphify",
    "handoff-to-new-chat",
    "id-tom-priemka",
    "image-text-replace",
    "karpathy-guidelines",
    "llm-interop",
    "local-osint-recon",
    "local-video-digest",
    "pd-tep-extractor",
    "pdf-edit",
    "pnr-vor-helper",
    "project-memory",
    "revit-family-generator",
    "revit-family-generator-ru",
    "revit-testbed",
    "ru-gov-access",
    "skill-development",
    "spec-writer",
    "stroy-formatting",
    "structured-artifacts",
    "supervisor",
    "supplier-due-diligence",
    "svor-vor-works-base",
    "understanding-map",
    "upd-parser",
    "web-access",
    "word-helper",
    "yandex-disk-uploader",
}


def test_catalog_exposes_exact_native_capability_set(repo_root):
    """Catches a dropped, duplicated, or accidentally added base capability."""
    catalog = load_catalog(repo_root)

    assert {item["id"] for item in catalog["agents"]} == EXPECTED_AGENT_IDS
    assert {item["id"] for item in catalog["skills"]} == EXPECTED_SKILL_IDS
    assert len(catalog["agents"]) == 16
    assert len(catalog["skills"]) == 37


def test_catalog_metadata_fits_worst_case_discovery_budget(repo_root):
    """Catches verbose descriptions that make Codex omit skills at startup."""
    catalog = load_catalog(repo_root)
    fake_home = Path(
        r"C:\Users\Employee-With-A-Deliberately-Long-Windows-Profile-Name"
    )

    for item in catalog["agents"] + catalog["skills"]:
        assert item["name"]
        assert item["description"]
        assert item["source"]
        assert isinstance(item["required_capabilities"], list)
    for item in catalog["skills"]:
        assert item["description"].startswith("Use when ")
        assert len(item["description"]) <= 180
    for item in catalog["agents"]:
        assert len(item["description"]) <= 240

    payload = estimate_discovery_payload(catalog, fake_home)
    assert payload["skill_chars"] <= 7200
    assert payload["agent_chars"] <= 4000
