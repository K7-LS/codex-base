from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

from openpyxl import Workbook
from openpyxl.worksheet.formula import ArrayFormula


ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT / "skills/stroy-formatting/tools/check_delivery.py"
EXCEL = ROOT / "skills/excel-helper/tools/excel_diff.py"


def run(script: Path, *args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        capture_output=True, encoding="utf-8", check=False,
    )


def test_delivery_blocks_internal_notes_in_docx_parts(tmp_path: Path):
    path = tmp_path / "delivery.docx"
    with ZipFile(path, "w") as package:
        package.writestr("word/document.xml", '<document><p><r><t>Акт готов.</t></r></p></document>')
        package.writestr(
            "word/header2.xml",
            '<hdr><p><r><t>Служебная </t></r><r><t>пометка: пересчитать объём</t></r></p></hdr>',
        )
    result = run(DELIVERY, path)
    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "BLOCKED"
    assert payload["findings"] == [{"location": "word/header2.xml", "code": "INTERNAL_NOTE"}]
    assert "пересчитать" not in result.stdout


def test_delivery_preserves_recipient_facts(tmp_path: Path):
    path = tmp_path / "answer.txt"
    path.write_text("Испытания не подтверждены. Приложение — лист замечаний.\n", encoding="utf-8")
    result = run(DELIVERY, path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"status": "PASS", "findings": []}


def test_delivery_checks_inline_and_shared_strings(tmp_path: Path):
    path = tmp_path / "delivery.xlsx"
    with ZipFile(path, "w") as package:
        package.writestr("xl/worksheets/sheet1.xml", '<worksheet><c><is><t>Акт готов.</t></is></c></worksheet>')
        package.writestr("xl/sharedStrings.xml", '<sst><si><r><t>Не для </t></r><r><t>выдачи</t></r></si></sst>')
    result = run(DELIVERY, path)
    assert result.returncode == 2, result.stderr
    assert json.loads(result.stdout)["findings"] == [
        {"location": "xl/sharedStrings.xml", "code": "INTERNAL_NOTE"}
    ]


def test_formula_guard_rejects_lost_formulas_and_changed_arrays(tmp_path: Path):
    before, after = tmp_path / "before.xlsx", tmp_path / "after.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = ArrayFormula("A1:A2", "=B1:B2")
    sheet["C10"] = "=1+2"
    workbook.create_sheet("Removed")["A1"] = "=1"
    workbook.save(before)
    del sheet["C10"]
    workbook.remove(workbook["Removed"])
    sheet["A1"] = ArrayFormula("A1:A2", "=D1:D2")
    workbook.save(after)
    original = before.read_bytes(), after.read_bytes()

    result = run(EXCEL, "formuladiff", before, after, "--require-unchanged")
    assert result.returncode == 2, result.stderr
    for location in ("Sheet!A1", "Sheet!C10", "Removed!A1"):
        assert location in result.stdout
    assert (before.read_bytes(), after.read_bytes()) == original

    ordinary = run(EXCEL, "formuladiff", before, after)
    assert ordinary.returncode == 0
    assert "3 formula diffs" in ordinary.stdout


def test_formula_guard_accepts_unchanged_formulas_and_ignores_literal_text(tmp_path: Path):
    before, after = tmp_path / "before.xlsx", tmp_path / "after.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "=SUM(B1:B2)"
    sheet["A2"] = ArrayFormula("A2:A3", "=B2:B3")
    sheet["C1"] = "=ordinary text"
    sheet["C1"].data_type = "s"
    workbook.save(before)
    sheet["C1"] = "edited text"
    workbook.save(after)

    result = run(EXCEL, "formuladiff", before, after, "--require-unchanged")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 formula diffs" in result.stdout


def test_delivery_checks_word_tracked_deletions(tmp_path: Path):
    path = tmp_path / "revision.docx"
    with ZipFile(path, "w") as package:
        package.writestr("word/document.xml", "<document><p><del><r><delText>Не для выдачи</delText></r></del></p></document>")
    result = run(DELIVERY, path)
    assert result.returncode == 2, result.stdout
    assert json.loads(result.stdout)["findings"] == [
        {"location": "word/document.xml", "code": "INTERNAL_NOTE"}
    ]


def test_delivery_checks_excel_headers_string_cache_and_drawing_text(tmp_path: Path):
    path = tmp_path / "delivery.xlsx"
    with ZipFile(path, "w") as package:
        package.writestr("xl/worksheets/sheet1.xml", "<worksheet><oddHeader>&amp;CНе для &amp;Bвыдачи</oddHeader></worksheet>")
        package.writestr("xl/worksheets/sheet2.xml", '<worksheet><c t="str"><v>Не для выдачи</v></c></worksheet>')
        package.writestr("xl/drawings/drawing1.xml", "<drawing><p><r><t>Не для выдачи</t></r></p></drawing>")
    result = run(DELIVERY, path)
    assert result.returncode == 2, result.stdout
    assert [item["location"] for item in json.loads(result.stdout)["findings"]] == [
        "xl/drawings/drawing1.xml", "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"
    ]


def test_delivery_does_not_mix_excel_header_sections(tmp_path: Path):
    path = tmp_path / "delivery.xlsx"
    with ZipFile(path, "w") as package:
        package.writestr(
            "xl/worksheets/sheet1.xml",
            "<worksheet><oddHeader>&amp;LНе для &amp;RВыдачи исполнены</oddHeader></worksheet>",
        )
    assert run(DELIVERY, path).returncode == 0


def test_delivery_checks_current_word_text_with_tracked_deletions(tmp_path: Path):
    path = tmp_path / "revision.docx"
    with ZipFile(path, "w") as package:
        package.writestr(
            "word/document.xml",
            "<document><p><r><t>Не для </t></r><del><r><delText>изъятия и </delText></r></del>"
            "<r><t>выдачи</t></r></p></document>",
        )
    assert run(DELIVERY, path).returncode == 2
