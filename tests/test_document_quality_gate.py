from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "document-quality-gate"
    / "scripts"
    / "quality_gate.py"
)


def _run(source: Path, receipt: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(source), "--receipt", str(receipt), *extra],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_empty_document_is_objectively_blocked(tmp_path: Path):
    source = tmp_path / "empty.txt"
    source.write_text("", encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    result = _run(source, receipt)
    assert result.returncode == 2
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["verdict"] == "BLOCKED"
    assert "EMPTY_CONTENT" in payload["objective_defects"]
    assert len(payload["result_sha256"]) == 64


def test_robotic_text_requires_named_human_review(tmp_path: Path):
    source = tmp_path / "draft.txt"
    source.write_text(
        "В рамках данного документа следует отметить важность вопроса.\n"
        "В рамках данного документа следует отметить важность результата.\n",
        encoding="utf-8",
    )
    receipt = tmp_path / "receipt.json"
    result = _run(source, receipt)
    assert result.returncode == 3
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["verdict"] == "REVIEW_REQUIRED"
    assert payload["style_warnings"]

    accepted = _run(
        source,
        receipt,
        "--review-verdict",
        "approved",
        "--reviewer",
        "Иванов И.И.",
        "--audit-verdict",
        "approved",
        "--auditor",
        "auditor",
    )
    assert accepted.returncode == 0
    assert json.loads(receipt.read_text(encoding="utf-8"))["verdict"] == "PASS"


def test_xlsx_without_print_area_is_reported_not_falsely_rendered(tmp_path: Path):
    source = tmp_path / "book.xlsx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Лист1" sheetId="1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Данные</t></is></c></row></sheetData></worksheet>',
        )
    receipt = tmp_path / "receipt.json"
    result = _run(source, receipt)
    assert result.returncode == 3
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert "XLSX_PRINT_AREA_NOT_DECLARED" in payload["style_warnings"]
    assert payload["renders"] == []
    assert payload["checks"]["visual_acceptance"] == "NOT_RUN"


def test_office_pass_requires_render_file_reviewer_and_source_auditor(tmp_path: Path):
    source = tmp_path / "book.xlsx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook><definedNames><definedName name='_xlnm.Print_Area'>S!A1</definedName></definedNames></workbook>")
        archive.writestr("xl/styles.xml", '<style wrapText="1"/>')
        archive.writestr("xl/worksheets/sheet1.xml", '<worksheet><pageSetup/><sheetData><row><c><v>1</v></c></row></sheetData></worksheet>')
    receipt = tmp_path / "receipt.json"
    render = tmp_path / "page-1.png"
    render.write_bytes(b"render")
    result = _run(
        source,
        receipt,
        "--render",
        str(render),
        "--file-review-verdict",
        "approved",
        "--file-reviewer",
        "excel-validator",
        "--audit-verdict",
        "approved",
        "--auditor",
        "auditor",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["verdict"] == "PASS"
    assert payload["file_review"]["reviewer"] == "excel-validator"
    assert payload["source_audit"]["auditor"] == "auditor"
