from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from openpyxl import Workbook
from openpyxl.worksheet.formula import ArrayFormula
from openpyxl.worksheet.pagebreak import Break


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


def test_plain_xlsx_rejects_workflow_note_and_optional_decimal_separator(tmp_path: Path):
    path = tmp_path / "Сверка.xlsx"
    book = Workbook()
    sheet = book.active
    sheet["A1"] = "Кабель объединён по указанию пользователя: 12 + 8 = 20 м."
    sheet["B1"] = 12
    sheet["C1"] = "=SUM(B1,8)"
    for cell in (sheet["B1"], sheet["C1"]):
        cell.number_format = "0.###"
    book.save(path)

    assert run(DELIVERY, path).returncode == 0
    result = run(DELIVERY, "--plain", path)
    assert result.returncode == 2
    assert json.loads(result.stdout)["findings"] == [
        {"location": "xl/worksheets/sheet1.xml", "code": "INTERNAL_NOTE"},
        {"location": "xl/worksheets/sheet1.xml!B1", "code": "OPTIONAL_DECIMAL_SEPARATOR"},
        {"location": "xl/worksheets/sheet1.xml!C1", "code": "OPTIONAL_DECIMAL_SEPARATOR"},
    ]
    assert "Кабель" not in result.stdout

    sheet["A1"] = "Итого по двум партиям — 20 м."
    sheet["B1"].number_format = "0"
    sheet["C1"].number_format = "General"
    sheet["B2"] = 12.5
    sheet["B2"].number_format = "0.0"
    book.save(path)
    assert run(DELIVERY, "--plain", path).returncode == 0


def test_delivery_directory_checks_only_agreed_files(tmp_path: Path):
    folder = tmp_path / "Выдача"
    folder.mkdir()
    (folder / "Письмо.docx").touch()
    (folder / "Реестр.xlsx").touch()
    args = (folder, "--expected", "Письмо.docx", "--expected", "Реестр.xlsx")
    assert run(DELIVERY, *args).returncode == 0
    extra = folder / "Основание" / "Акт испытаний.txt"
    extra.parent.mkdir()
    extra.touch()
    (folder / "Реестр.xlsx").unlink()
    result = run(DELIVERY, *args)
    assert result.returncode == 2
    assert json.loads(result.stdout)["findings"] == [
        {"location": "Основание/Акт испытаний.txt", "code": "UNEXPECTED_FILE"},
        {"location": "Реестр.xlsx", "code": "MISSING_FILE"},
    ]


@pytest.mark.parametrize("ns", [
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
])
def test_plain_delivery_blocks_inherited_theme_border_only_when_applied(tmp_path: Path, ns: str):
    path = tmp_path / "letter.docx"
    styles = f'''<w:styles xmlns:w="{ns}">
      <w:style w:type="paragraph" w:styleId="Base">
        <w:pPr><w:pBdr><w:bottom w:val="single" w:color="4F81BD" w:themeColor="accent1"/></w:pBdr></w:pPr>
      </w:style>
      <w:style w:type="paragraph" w:styleId="Title"><w:basedOn w:val="Base"/></w:style>
    </w:styles>'''
    for paragraph, expected in [
        ('<w:pStyle w:val="Title"/>', 2),
        ('<w:pStyle w:val="Title"/><w:pBdr><w:top w:val="single" w:color="000000"/></w:pBdr>', 2),
        ('<w:pStyle w:val="Title"/><w:pBdr><w:bottom w:val="nil"/></w:pBdr>', 0),
        ('<w:pBdr><w:bottom w:val="single" w:color="000000"/></w:pBdr>', 0),
    ]:
        with ZipFile(path, "w") as package:
            package.writestr("word/styles.xml", styles)
            package.writestr(
                "word/document.xml",
                f'<w:document xmlns:w="{ns}"><w:body><w:p><w:pPr>{paragraph}</w:pPr>'
                '<w:r><w:t>Реестр</w:t></w:r></w:p></w:body></w:document>',
            )
        assert run(DELIVERY, path).returncode == 0
        result = run(DELIVERY, "--plain", path)
        assert result.returncode == expected, result.stderr
        if expected:
            assert json.loads(result.stdout)["findings"] == [
                {"location": "word/document.xml", "code": "NON_NEUTRAL_PARAGRAPH_BORDER"}
            ]


def test_plain_template_title_has_black_times_new_roman_and_no_border(tmp_path: Path):
    template = ROOT / "skills/stroy-formatting/assets/templates/plain-clean.docx"
    path = tmp_path / "letter.docx"
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    w = f"{{{ns}}}"
    with ZipFile(template) as package:
        styles = package.read("word/styles.xml")
    with ZipFile(path, "w") as package:
        package.writestr("word/styles.xml", styles)
        package.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{ns}"><w:body><w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr>'
            '<w:r><w:t>Реестр</w:t></w:r></w:p></w:body></w:document>',
        )
    assert run(DELIVERY, "--plain", path).returncode == 0
    title = ET.fromstring(styles).find(f"{w}style[@{w}styleId='Title']/{w}rPr")
    assert title.find(f"{w}rFonts").get(f"{w}hAnsi") == "Times New Roman"
    assert title.find(f"{w}color").attrib == {f"{w}val": "000000"}


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


def test_print_guard_rejects_resave_that_enables_fit_to_page(tmp_path: Path):
    before, after = tmp_path / "before.xlsx", tmp_path / "after.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Образец"
    sheet.print_area = "A1:D4"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    workbook.save(before)

    sheet.title = "ВОР"
    sheet["D3"] = 20.5
    workbook.save(after)
    result = run(EXCEL, "printdiff", before, after, "Образец", "ВОР")
    assert result.returncode == 0, result.stdout + result.stderr

    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 1
    sheet.row_breaks.append(Break(id=6))
    sheet.oddFooter.center.text = "Внутренний текст колонтитула"
    workbook.save(after)
    final_bytes = after.read_bytes()
    result = run(EXCEL, "printdiff", before, after, "Образец", "ВОР")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "fitToPage" in result.stdout
    assert "fitToWidth" in result.stdout
    assert "row_breaks" in result.stdout
    assert "header_footer.oddFooter.sha256" in result.stdout
    assert "Внутренний текст" not in result.stdout
    assert after.read_bytes() == final_bytes

    unknown_sheet = run(EXCEL, "printdiff", before, after, "Образец", "Нет листа")
    assert unknown_sheet.returncode == 1
    assert "Нет листа" in unknown_sheet.stderr


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
