#!/usr/bin/env python3
"""excel-helper Layer-3 — стабильные детерминированные функции для xlsx.

Вынесено из SKILL.md (skill-development правило 2: повторяемая логика → tools/),
чтобы не переписывать заново каждый раз (риск ошибки при ручном воспроизведении).

Функции (importable):
  cell_diff(v1, v2, out)        — cell-by-cell diff с подсветкой, новый xlsx
  formula_diff(v1, v2)          — расхождения формул как текст (не значений)
  find_formula_errors(path)     — найти #REF!/#DIV/0!/#NAME? (по cached-значениям)
  find_duplicates(path, key)    — дубликаты по колонке-ключу (pandas)

CLI:
  python excel_diff.py celldiff  v1.xlsx v2.xlsx out.xlsx
  python excel_diff.py formuladiff v1.xlsx v2.xlsx [--require-unchanged]
  python excel_diff.py printdiff reference.xlsx final.xlsx reference_sheet final_sheet
  python excel_diff.py errors    file.xlsx
  python excel_diff.py dupes     file.xlsx ID

Ловушки (см. SKILL.md): data_only=True вернёт None для формул без кэша Excel;
openpyxl save() стирает drawing-слой (картинки) и ломает vertical-merge при delete_rows.
Эти функции — read/diff (errors, formuladiff, printdiff, dupes безопасны); cell_diff пишет НОВЫЙ
файл из v2, для файлов с картинками проверь media-слой перед использованием результата.
"""
import sys
import io

# UTF-8 stdout (кириллица в выводе на Windows-консоли)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def cell_diff(v1_path, v2_path, out_path):
    """Открывает v2 как базу (он 'новый'), сравнивает с v1, заливает изменённые
    ячейки. Возвращает счётчики по типам различий. Структура листов — как в v2."""
    from openpyxl import load_workbook
    from openpyxl.styles import PatternFill

    YELLOW = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")  # изменилось
    GREEN = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")   # добавилось (в v2, нет в v1)
    RED = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")     # удалилось (в v1, нет в v2)

    wb1 = load_workbook(v1_path, data_only=False)
    wb2 = load_workbook(v2_path, data_only=False)
    stats = {"changed": 0, "added": 0, "removed": 0,
             "sheets_only_in_v2": [], "sheets_only_in_v1": []}

    for name in wb2.sheetnames:
        if name not in wb1.sheetnames:
            stats["sheets_only_in_v2"].append(name)
            continue
        ws1, ws2 = wb1[name], wb2[name]
        max_row = max(ws1.max_row, ws2.max_row)
        max_col = max(ws1.max_column, ws2.max_column)
        for r in range(1, max_row + 1):
            for c in range(1, max_col + 1):
                v1 = ws1.cell(r, c).value
                v2 = ws2.cell(r, c).value
                if v1 == v2:
                    continue
                target = ws2.cell(r, c)
                if v1 is None and v2 is not None:
                    target.fill = GREEN
                    stats["added"] += 1
                elif v1 is not None and v2 is None:
                    target.fill = RED
                    target.value = f"[DELETED] was: {v1}"
                    stats["removed"] += 1
                else:
                    target.fill = YELLOW
                    stats["changed"] += 1

    for name in wb1.sheetnames:
        if name not in wb2.sheetnames:
            stats["sheets_only_in_v1"].append(name)

    wb2.save(out_path)
    return stats


def _formula_inventory(path):
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    try:
        formulas = {}
        for sheet in workbook.worksheets:
            # Read actual rows even when the producer saved a stale used range.
            sheet.reset_dimensions()
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.data_type == "f":
                        value = cell.value
                        formulas[sheet.title, cell.coordinate] = (
                            value if isinstance(value, str)
                            else repr((dict(value), getattr(value, "text", None)))
                        )
        return formulas
    finally:
        workbook.close()


def formula_diff(v1_path, v2_path):
    """Расхождения формул по листам и адресам, включая удалённые и добавленные."""
    before, after = _formula_inventory(v1_path), _formula_inventory(v2_path)
    return [
        (sheet, coordinate, before.get((sheet, coordinate)), after.get((sheet, coordinate)))
        for sheet, coordinate in sorted(before.keys() | after.keys())
        if before.get((sheet, coordinate)) != after.get((sheet, coordinate))
    ]


def _print_settings(path, sheet_name):
    from hashlib import sha256

    from openpyxl import load_workbook
    from openpyxl.utils.cell import quote_sheetname

    workbook = load_workbook(path, keep_links=False)
    try:
        sheet = workbook[sheet_name]
        qualifier = f"{quote_sheetname(sheet.title)}!"
        settings = {
            "print_area": sheet.print_area.replace(qualifier, ""),
            "print_title_rows": sheet.print_title_rows,
            "print_title_cols": sheet.print_title_cols,
            "row_breaks": [dict(item) for item in sheet.row_breaks.brk],
            "column_breaks": [dict(item) for item in sheet.col_breaks.brk],
        }
        for section, value in (
            ("page_setup", sheet.page_setup),
            ("page_margins", sheet.page_margins),
            ("print_options", sheet.print_options),
            ("page_setup_properties", sheet.sheet_properties.pageSetUpPr),
            ("header_footer", sheet.HeaderFooter),
        ):
            if value is not None:
                settings.update((f"{section}.{key}", entry) for key, entry in value)
        for name in ("oddHeader", "evenHeader", "firstHeader", "oddFooter", "evenFooter", "firstFooter"):
            content = str(getattr(sheet.HeaderFooter, name))
            if content:
                settings[f"header_footer.{name}.sha256"] = sha256(content.encode("utf-8")).hexdigest()
        return settings
    finally:
        workbook.close()


def print_diff(reference_path, final_path, reference_sheet, final_sheet):
    """Сравнить настройки печати двух листов без пересохранения книг."""
    before = _print_settings(reference_path, reference_sheet)
    after = _print_settings(final_path, final_sheet)
    return [
        (key, before.get(key), after.get(key))
        for key in sorted(before.keys() | after.keys())
        if before.get(key) != after.get(key)
    ]


def find_formula_errors(path):
    """Найти ячейки с ошибками #REF!/#DIV/0!/#NAME? по cached-значениям.
    ВНИМАНИЕ: требует, чтобы файл был открыт/сохранён в Excel (иначе кэша нет
    и формулы вернут None). Возвращает [(sheet, coord, error), ...]."""
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    errors = []
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        for row in ws.iter_rows():
            for cell in row:
                if cell.value and isinstance(cell.value, str) and cell.value.startswith("#"):
                    errors.append((sheet, cell.coordinate, cell.value))
    return errors


def find_duplicates(path, key, sheet_name=0):
    """Дубликаты по колонке-ключу. Возвращает pandas.DataFrame дублей."""
    import pandas as pd
    df = pd.read_excel(path, sheet_name=sheet_name)
    dups = df[df.duplicated(subset=[key], keep=False)]
    return dups.sort_values(key)


def _main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == "celldiff" and len(argv) == 5:
        print(cell_diff(argv[2], argv[3], argv[4]))
    elif cmd == "formuladiff" and (len(argv) == 4 or argv[4:] == ["--require-unchanged"]):
        rows = formula_diff(argv[2], argv[3])
        for sheet, coord, f1, f2 in rows:
            print(f"{sheet}!{coord}:\n  v1: {f1}\n  v2: {f2}")
        print(f"\n{len(rows)} formula diffs")
        if len(argv) == 5 and rows:
            return 2
    elif cmd == "printdiff" and len(argv) == 6:
        try:
            rows = print_diff(*argv[2:])
        except KeyError as error:
            print(error, file=sys.stderr)
            return 1
        for key, before, after in rows:
            print(f"{key}: {before!r} → {after!r}")
        print(f"{len(rows)} print setting diffs")
        return 2 if rows else 0
    elif cmd == "errors" and len(argv) == 3:
        errs = find_formula_errors(argv[2])
        for s, c, e in errs:
            print(f"{s}!{c}: {e}")
        print(f"\n{len(errs)} formula errors")
    elif cmd == "dupes" and len(argv) == 4:
        print(find_duplicates(argv[2], argv[3]).to_string())
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
