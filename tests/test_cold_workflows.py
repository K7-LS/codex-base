"""Cold instruction contracts and an executable, deliberately narrow OOXML example.

These checks catch broken routes/operation labels and verify the actual example
against XML fixtures. They do not simulate an LLM, Word rendering, or Revit MCP.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def stage(relative: str, number: int) -> str:
    text = read(relative)
    return re.search(
        rf"(?ms)^### Stage {number}\b.*?(?=^### Stage |^## |\Z)", text
    ).group(0)


@pytest.mark.parametrize("relative", [
    "cold/chains/docx-from-template.md",
    "cold/chains/pdf-scan-extract.md",
    "cold/chains/upd-to-spec-reconcile.md",
    "cold/memory/reference_revit_mcp.md",
    "skills/word-helper/SKILL.md",
    "skills/excel-helper/SKILL.md",
])
def test_capability_labels_have_valid_inline_code_boundaries(relative: str):
    # A capability ID belongs inside one code span, not a nested code span
    # accidentally produced by mechanical replacement of a provider tool name.
    broken = re.findall(r"(?m)^.*`capability\s+`[^\n]+$", read(relative))
    assert not broken, (relative, broken)


@pytest.mark.parametrize("relative,number,operation", [
    ("cold/chains/docx-from-template.md", 3, "document.word"),
    ("cold/chains/upd-to-spec-reconcile.md", 5, "spreadsheet"),
])
def test_mutation_stage_requires_write_operation(relative, number, operation):
    identifiers = set(re.findall(r"`([a-z][a-z.]+)`", stage(relative, number)))
    assert f"{operation}.write" in identifiers, identifiers
    # A read operation may verify a write, but cannot be its only provider route.
    assert identifiers != {f"{operation}.read"}


def test_revit_selector_cannot_treat_capability_as_a_provider_name():
    selectors = re.findall(r"select:([^\n]+)", read("cold/memory/reference_revit_mcp.md"))
    assert all("capability" not in value and "revit.inspect" not in value
               for value in selectors), selectors


def test_active_chain_index_entries_exist_and_are_active():
    rows = [line for line in read("cold/memory/named_chains.md").splitlines()
            if "✅" in line]
    assert rows
    for line in rows:
        name = re.search(r"`chain:([a-z0-9-]+)`", line).group(1)
        target = ROOT / "cold/chains" / f"{name}.md"
        assert target.is_file(), f"Advertised active chain is absent: {name}"
        assert re.search(r"(?m)^status:\s*active\s*$", target.read_text(encoding="utf-8"))


def test_chain_index_installed_paths_resolve_to_actual_payload_sources():
    paths = re.findall(r"`(~/.codex/base/[^`]+)`", read("cold/memory/named_chains.md"))
    assert paths
    for path in paths:
        # release.py places cold/ at .codex/base/cold; no legacy chains alias.
        target = ROOT / path.removeprefix("~/.codex/base/")
        assert target.exists(), f"Unpackaged instruction path: {path}"


@pytest.fixture
def replace_example():
    # Execute only the named function definition, never file-opening examples.
    blocks = re.findall(r"```python\s*\n(.*?)\n```", read("skills/word-helper/SKILL.md"), re.S)
    functions = [node for block in blocks if "def replace_text_only_paragraph(" in block
                 for node in ast.parse(block).body
                 if isinstance(node, ast.FunctionDef)
                 and node.name == "replace_text_only_paragraph"]
    assert len(functions) == 1, "The supported replacement example must be independently executable"
    namespace = {}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "word-helper-example", "exec"), namespace)
    return namespace["replace_text_only_paragraph"]


def paragraph(*runs: tuple[str, str]) -> ET.Element:
    p = ET.Element(W + "p")
    for text, style in runs:
        run = ET.SubElement(p, W + "r")
        props = ET.SubElement(run, W + "rPr")
        ET.SubElement(props, W + style)
        ET.SubElement(run, W + "t").text = text
    return p


def test_cross_run_replacement_preserves_surrounding_text_and_run_properties(replace_example):
    p = paragraph(("До {{НА", "b"), ("МЕ}} после", "i"))
    props_before = [ET.tostring(r.find(W + "rPr")) for r in p]
    assert replace_example(p, "{{НАМЕ}}", "Иван & <сын>") == 1
    assert [r.find(W + "t").text for r in p] == ["До Иван & <сын>", " после"]
    assert [ET.tostring(r.find(W + "rPr")) for r in p] == props_before
    assert "".join(ET.fromstring(ET.tostring(p)).itertext()) == "До Иван & <сын> после"


def test_missing_placeholder_does_not_rewrite_paragraph(replace_example):
    p = paragraph(("Неизменяемый текст", "b"))
    before = ET.tostring(p)
    assert replace_example(p, "{{name}}", "Значение") == 0
    assert ET.tostring(p) == before


@pytest.mark.parametrize("tag", ["tab", "br", "drawing", "fldChar"])
def test_complex_run_is_rejected_without_removing_nontext_nodes(replace_example, tag):
    p = paragraph(("{{name}}", "u"))
    ET.SubElement(p[0], W + tag)
    before = ET.tostring(p)
    with pytest.raises(ValueError):
        replace_example(p, "{{name}}", "Новый текст")
    assert ET.tostring(p) == before


def test_hyperlink_is_rejected_without_flattening(replace_example):
    p = paragraph(("{{name}}", "b"))
    ET.SubElement(p, W + "hyperlink")
    before = ET.tostring(p)
    with pytest.raises(ValueError):
        replace_example(p, "{{name}}", "Значение")
    assert ET.tostring(p) == before


def test_ambiguous_repeated_placeholder_is_rejected_before_mutation(replace_example):
    p = paragraph(("{{name}} и {{name}}", "b"))
    before = ET.tostring(p)
    with pytest.raises(ValueError):
        replace_example(p, "{{name}}", "Значение")
    assert ET.tostring(p) == before


def test_empty_placeholder_is_rejected(replace_example):
    p = paragraph(("Оригинал", "i"))
    before = ET.tostring(p)
    with pytest.raises(ValueError):
        replace_example(p, "", "Значение")
    assert ET.tostring(p) == before


def test_overlapping_matches_are_rejected_before_mutation(replace_example):
    p = paragraph(("aaa", "b"))
    before = ET.tostring(p)
    with pytest.raises(ValueError):
        replace_example(p, "aa", "X")
    assert ET.tostring(p) == before


@pytest.mark.parametrize("control", ["\r", "\n", "\t"])
def test_structural_new_value_is_rejected_by_text_only_example(replace_example, control):
    p = paragraph(("{{name}}", "b"))
    before = ET.tostring(p)
    with pytest.raises(ValueError):
        replace_example(p, "{{name}}", "Иван" + control + "Иванов")
    assert ET.tostring(p) == before


def test_replacement_keeps_significant_spaces(replace_example):
    p = paragraph(("{{name}}", "u"))
    assert replace_example(p, "{{name}}", " Иван ") == 1
    t = p[0].find(W + "t")
    assert t.text == " Иван "
    assert t.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"
