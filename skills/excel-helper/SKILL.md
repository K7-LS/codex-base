---
name: excel-helper
description: Use when нужно прочитать, изменить или проверить XLSX.
---

# excel-helper

## Когда подключаться

Любая задача с `.xlsx` где нужно понять структуру, найти ошибки, сравнить, посчитать. Если просто «открой файл и покажи первую строку» — Read tool через MCP excel хватит, без скилла.

## Иерархия инструментов

| Задача | Инструмент | Заметка |
|--------|------------|---------|
| CRUD ячеек, листов, форматов | `excel-mcp-server` | Стандартный путь для **малых** диапазонов (<50 строк × 10 кол.) |
| Чтение/анализ **больших** таблиц | Python `openpyxl` / PS | excel MCP read раздувает JSON и упирается в token-лимit — см. ловушку 9 |
| Анализ всего файла, агрегации | Python `openpyxl` | Когда нужны цикл/условия/перебор сотен строк |
| Сравнение двух файлов | Python `pandas` | DataFrame.compare() или merge + diff |
| Большие файлы (>100к строк) | Python `pandas` с `chunksize` или `polars` | openpyxl читает медленно |
| Чтение формул как текст vs значений | `openpyxl` с `data_only=False` (формулы) или `data_only=True` (значения) | По умолчанию формулы |
| Запись формул | excel-mcp поддерживает; openpyxl: `cell.value = "=SUM(A1:A10)"` | Excel пересчитает при открытии |

## Tools (слой 3) — готовые скрипты, не переписывать inline

Стабильные детерминированные функции вынесены в `tools/excel_diff.py`
(skill-development правило 2). Сначала использовать их, не воспроизводить
код заново — ниже по тексту те же функции дублируются как справка/для
кастомизации, но рабочий путь — готовый скрипт:

```bash
python skills/excel-helper/tools/excel_diff.py celldiff  v1.xlsx v2.xlsx out.xlsx   # diff с подсветкой
python skills/excel-helper/tools/excel_diff.py formuladiff v1.xlsx v2.xlsx          # расхождения формул
python skills/excel-helper/tools/excel_diff.py errors    file.xlsx                  # #REF!/#DIV/0!/#NAME?
python skills/excel-helper/tools/excel_diff.py dupes     file.xlsx ID               # дубликаты по ключу
```

Или `import`: `cell_diff`, `formula_diff`, `find_formula_errors`, `find_duplicates`.
Запускать Python'ом с установленными `openpyxl`/`pandas` (системный, не uv-tool graphify).

## БОЕВОЕ ПРАВИЛО чтения чужого файла: сначала формулы, потом выводы

Перед ЛЮБЫМ анализом значений (особенно денег) в существующем xlsx — обязательный скан:

```python
wb_f = load_workbook(path, data_only=False)   # формулы как текст
wb_v = load_workbook(path, data_only=True)    # кэшированные значения
# ячейка: формула есть (str, начинается с "="), а в wb_v там None →
# кэша НЕТ (файл не открывался в Excel после записи формул)
```

- `None` при `data_only=True` ≠ «ячейка пустая». Это может быть формула без кэша.
  Заявить «тут пусто» на формульной ячейке = инцидент класса «расхождение 10000% по деньгам» (реальный кейс 2026-06).
- Формулы есть, кэша нет → **выводы о значениях запрещены**. Сказать пользователю:
  «файл нужно открыть и сохранить в Excel» либо пересчитать формулы самому (Python)
  и пометить результат как свой пересчёт, не как содержимое файла.
- Итоговые суммы по деньгам — всегда подтверждать независимым пересчётом
  (сложить числовые ячейки самому и сравнить с итоговой формулой/значением).

## Оформление — нейтральное, БЕЗ декоративного синего стиля

**Мы серьёзная компания.** НЕ применять «синий Codex-стиль» к деловым xlsx (синие
шапки таблиц, банды, акцентные заливки/шрифты). По умолчанию:

- **Таблицы:** openpyxl `Table` с дефолтным `TableStyleInfo` даёт **синий**
  `TableStyleMedium2/9` — НЕ использовать. Либо вообще без table-style, либо
  нейтральный (`TableStyleLight1` / без цвета). Лучше — простые границы вручную.
- **Шапка:** жирный + максимум светло-серая заливка (`F2F2F2`/`D9D9D9`), **чёрный**
  текст, тонкие серо-чёрные границы. Никакого синего/акцентного.
- **При правке существующего файла** — наследовать стиль книги, НЕ навязывать свой.
- **Цвет ТОЛЬКО** если: есть в источнике, попросил пользователь, ИЛИ это
  функциональная подсветка анализа (diff yellow/green/red, подсветка ошибок —
  это рабочий инструмент, НЕ для сдачи заказчику).

## Типовые задачи

### Найти расхождения между двумя файлами (pandas — табличный diff)

```python
import pandas as pd
df1 = pd.read_excel("v1.xlsx", sheet_name="Sheet1")
df2 = pd.read_excel("v2.xlsx", sheet_name="Sheet1")

# Если ключ — колонка "ID":
merged = df1.merge(df2, on="ID", how="outer", indicator=True, suffixes=("_v1", "_v2"))
print(merged[merged["_merge"] != "both"])  # что добавилось/удалилось

# Расхождения в общих строках:
common = merged[merged["_merge"] == "both"]
for col in [c for c in df1.columns if c != "ID"]:
    diff = common[common[f"{col}_v1"] != common[f"{col}_v2"]]
    if not diff.empty:
        print(f"\n=== {col} ===")
        print(diff[["ID", f"{col}_v1", f"{col}_v2"]])
```

### Cell-by-cell diff с подсветкой в новом xlsx

Когда нужно **визуально** показать что изменилось — итерация по совпадающим листам, цветовая подсветка изменённых ячеек, добавленных строк, удалённых строк. Структура листов считается одинаковой.

```python
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
from copy import copy

YELLOW = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")  # изменилось
GREEN  = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")  # добавилось (есть в v2, нет в v1)
RED    = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")  # удалилось (есть в v1, нет в v2)

def cell_diff(v1_path: str, v2_path: str, out_path: str) -> dict:
    """
    Открывает v2 как базу (он "новый"), сравнивает с v1, заливает изменённые ячейки.
    Возвращает счётчики по типам различий.
    """
    wb1 = load_workbook(v1_path, data_only=False)
    wb2 = load_workbook(v2_path, data_only=False)
    stats = {"changed": 0, "added": 0, "removed": 0, "sheets_only_in_v2": [], "sheets_only_in_v1": []}

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
```

**Применение:**
```python
stats = cell_diff("v1.xlsx", "v2.xlsx", "diff_highlighted.xlsx")
print(stats)  # {'changed': 12, 'added': 3, 'removed': 1, ...}
```

### Formula-level diff (формулы vs значения)

Когда расхождение в **самой формуле**, а не в её значении — стандартный `data_only=True` это скроет. Сравниваем формулы как текст, отдельно от cached-значений.

```python
from openpyxl import load_workbook

def formula_diff(v1_path: str, v2_path: str) -> list:
    """
    Возвращает список расхождений в формулах: [(sheet, A1, formula_v1, formula_v2), ...].
    Только те ячейки, где хотя бы в одном из файлов есть формула.
    """
    wb1 = load_workbook(v1_path, data_only=False)
    wb2 = load_workbook(v2_path, data_only=False)
    out = []
    for name in set(wb1.sheetnames) & set(wb2.sheetnames):
        ws1, ws2 = wb1[name], wb2[name]
        for row in ws2.iter_rows():
            for cell in row:
                f2 = cell.value if isinstance(cell.value, str) and cell.value.startswith("=") else None
                f1_val = ws1.cell(cell.row, cell.column).value
                f1 = f1_val if isinstance(f1_val, str) and f1_val.startswith("=") else None
                if f1 != f2 and (f1 or f2):
                    out.append((name, cell.coordinate, f1, f2))
    return out

for sheet, coord, f1, f2 in formula_diff("v1.xlsx", "v2.xlsx"):
    print(f"{sheet}!{coord}:")
    print(f"  v1: {f1}")
    print(f"  v2: {f2}")
```

**Ловушка:** если ячейка в v1 содержит формулу `=SUM(A1:A10)` со значением `55`, а в v2 — просто число `55` (формула удалена, оставлено значение) — `formula_diff` это поймает (`f1` есть, `f2` нет). Это и есть нужное поведение: пользователь часто хочет знать, где формула "захардкожена" в значение.

### Валидация формул — найти #REF! / #DIV/0! / #NAME?

```python
from openpyxl import load_workbook
wb = load_workbook("file.xlsx", data_only=True)  # data_only=True вернёт CACHED значения
errors = []
for sheet in wb.sheetnames:
    ws = wb[sheet]
    for row in ws.iter_rows():
        for cell in row:
            if cell.value and isinstance(cell.value, str) and cell.value.startswith("#"):
                errors.append((sheet, cell.coordinate, cell.value))
for e in errors:
    print(f"{e[0]}!{e[1]}: {e[2]}")
```

**Важно**: чтобы Excel пересчитал и закэшировал значения, файл должен быть открыт и сохранён в Excel хотя бы один раз. Если файл создан Python — `data_only=True` вернёт `None` для формул.

### Найти дубликаты по ключу

```python
import pandas as pd
df = pd.read_excel("file.xlsx")
dups = df[df.duplicated(subset=["ID"], keep=False)]
print(dups.sort_values("ID"))
```

### Найти циркулярные ссылки

`openpyxl` напрямую их не флагует. Косвенный признак: в `data_only=True` mode значение ячейки `0` или `None`, а в `data_only=False` mode — формула, ссылающаяся (прямо или транзитивно) на саму себя. Простой эвристический поиск:

```python
import re
from openpyxl import load_workbook
wb = load_workbook("file.xlsx", data_only=False)
for ws in wb.worksheets:
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and cell.value.startswith("="):
                # Самопрямая ссылка:
                if cell.coordinate in cell.value:
                    print(f"Self-ref: {ws.title}!{cell.coordinate} = {cell.value}")
```

### Условное форматирование (выделить ошибки)

`excel-mcp` это умеет. Через Python:

```python
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
wb = load_workbook("file.xlsx")
ws = wb["Sheet1"]
red = PatternFill(start_color="FFCCCC", end_color="FFCCCC", fill_type="solid")
for row in ws.iter_rows(min_row=2):
    for cell in row:
        if cell.value is None:
            cell.fill = red
wb.save("highlighted.xlsx")
```

## Ловушки

1. **Locale (русская)** — формулы хранятся английскими функциями (`SUM`, `IF`), а отображаются `СУММ`, `ЕСЛИ`. При записи через Python — пиши на английском, Excel сам переведёт.
2. **Десятичный разделитель** — в русской локали запятая, в файлах CSV. Pandas: `pd.read_csv(..., decimal=",")`.
3. **Кодировка CSV от 1С** — обычно `cp1251` (Windows-1251). Если получишь "Я€" вместо русских — `encoding="cp1251"`.
4. **Дата в Excel — это число** (с 1900-01-01 = 1). При сравнении дат в pandas из xlsx — конвертировать через `pd.to_datetime()`.
5. **Пустые ячейки vs `None` vs `0`** — openpyxl возвращает `None` для пустых, `pandas` — `NaN`. Не путать с `0`.
6. **Объединённые ячейки (merged)** — значение хранится только в верхней-левой ячейке диапазона; остальные `None`. Для итерации `for row in ws.iter_rows()` придётся unmerge или пробрасывать значение из якоря.
7. **Большие файлы** — `openpyxl` читает медленно (~1 сек на 10к строк). Для >100к строк — `pandas.read_excel` с движком `openpyxl` или `polars`.
8. **Запись через openpyxl стирает условное форматирование и сводные**, если их не загрузить с `keep_vba=True` и не пересохранить аккуратно. Лучше править через excel-mcp.
9. **excel MCP read на больших таблицах → «exceeds maximum tokens».** `capability `spreadsheet.read`` раздувает JSON метаданными валидации/формул и упирается в token-лимит (наблюдалось **64–74K токенов на один лист**). Подтверждено независимо ≥3 раза (замечания Химки, серия ПНР+ВОР <объект-A>, СОТ). **Правило: >50 строк → читать через openpyxl напрямую или PowerShell + `ConvertFrom-Json`, НЕ через MCP read.** MCP read оставлять для малых диапазонов (<50×10), где он удобнее.

```powershell
# Большой лист через openpyxl (UTF-8 stdout обязательно):
$env:PYTHONIOENCODING="utf-8"; python -c @"
import sys; sys.stdout.reconfigure(encoding='utf-8')
from openpyxl import load_workbook
ws = load_workbook(r'path.xlsx', data_only=False)['ВОР']
for r, row in enumerate(ws.iter_rows(values_only=True), 1):
    if any(c is not None for c in row): print(f'{r}:', row)
"@
```
10. **Формулы через excel MCP — только `apply_formula`, НЕ `write_data_to_excel`.**
    Если записать `=J96*0.2` через `write_data_to_excel`, оно сохранится как **строка-текст**,
    не формула. Использовать `capability `spreadsheet.read``. И ещё — **RU-запятая ломает
    формулу:** `=J96*0,2` (запятая) не парсится как формула → писать с **точкой**
    (`=J96*0.2`), Excel сам отобразит по локали. (Источник: muzey-spartak, <шифр>.)
11. **Старый `.xls` (BIFF) — читать `xlrd`, не openpyxl.** openpyxl работает только с
    `.xlsx` (OOXML). Для `.xls` (Excel 97-2003) — `xlrd` (`import xlrd; xlrd.open_workbook(...)`).
    Источники спецификаций нередко приходят в старом `.xls`.
12. **INDIRECT / лист «На печать» — не ломать косвенные ссылки.** В некоторых
    спецификациях видимый лист («На печать») собирается формулами `INDIRECT`/ссылками с
    лист-доноров. Правка значения «в лоб» на печатном листе затирает формулу. **Donor-pattern
    восстановления:** если hard-coded формула затёрта — взять её из соседней строки-донора
    того же столбца (где формула цела), подставить с корректировкой индексов строки.
13. **Запись блоками — считать строки, не «по памяти».** Запись `write_data_to_excel`
    со `start_cell` без точного учёта числа строк блока затирает соседние позиции
    (наблюдалось: зал-3 с A22 затёр позицию 2.9). Лучше: вывести данные с фиксированными
    координатами / `insert_rows` перед вставкой; после — read-back verify (ниже).
14. **OnlyOffice / Р7-Офис НЕ выполняют Power Query и LAMBDA** (импортозамещение). Сложные
    xlsx с PQ/динамическими массивами/LAMBDA в них ломаются/не считаются. Если файл
    заказчика на этих движках — проверить, нет ли PQ/LAMBDA; критичную логику дублировать
    обычными формулами. M365 — тянет; OnlyOffice — нет. (Источник: collaborative-excel-tools, <шифр>.)
15. **`openpyxl`/excel MCP при `save()` молча УДАЛЯЕТ drawing-слой (картинки/лого).**
    Любая запись в xlsx с встроенными изображениями через `Workbook.save()` или
    `capability `spreadsheet.read`` → картинки исчезают (реальный кейс: пропало 30+ лого
    из каталога вендоров). **Pre-flight:** до записи проверить ZIP-разведкой наличие
    `xl/media/*` и `xl/drawings/*.xml`:
    ```powershell
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($path)
    $media = @($zip.Entries | Where-Object { $_.FullName -like "xl/media/*" }).Count
    $zip.Dispose(); Write-Host "media images: $media"
    ```
    Если drawings есть — НЕ писать через MCP/`save()`. Варианты: (а) запись через **ZIP-хирургию**
    (правка `xl/media/`, `xl/drawings/drawingN.xml`, `_rels`, `[Content_Types].xml` напрямую в
    архиве в режиме Update); (б) правки делает пользователь в Excel. Post-verify: media-count
    ПОСЛЕ == media-count ДО (+ ровно новые). Поле `descr` в drawing.xml Excel не обновляет —
    сверять по SHA-256 содержимого, не по метаданным. (Источник: feedback vendor-logo-inserter.)
16. **`delete_rows()` на листе с ВЕРТИКАЛЬНЫМИ merge молча теряет данные.** openpyxl при
    `ws.delete_rows()` пытается сдвинуть merge-диапазоны и при высокой плотности
    вертикальных merge (поз. занимает 2+ строки, merge колонок A/B/J/K) **клобберит
    значения ячеек ниже точки удаления**. Баг тихий: файл открывается, нумерация якорей
    «выглядит» непрерывной, но данные пропали (реальный кейс: удалили 15 позиций — пропало
    ещё 35 соседних наименований/цен; ВОР 2300+ merge). **Паттерн безопасного удаления:**
    ```python
    import bisect
    deleted = sorted(set(rows_to_delete))                       # 1-based номера строк
    has_vmerge = any(m.max_row > m.min_row for m in ws.merged_cells.ranges)
    if has_vmerge:
        ranges = [(m.min_row, m.min_col, m.max_row, m.max_col)  # 1) snapshot всех merge
                  for m in ws.merged_cells.ranges]
        for m in list(ws.merged_cells.ranges):                   # 2) unmerge ВСЕ
            ws.unmerge_cells(str(m))
        for r in reversed(deleted):                              # 3) теперь чистый сдвиг значений
            ws.delete_rows(r, 1)
        for (r1, c1, r2, c2) in ranges:                          # 4) пересчёт смещения и re-merge
            if all(r in deleted for r in range(r1, r2 + 1)):
                continue                                         # merge целиком удалён → drop
            n1 = r1 - bisect.bisect_left(deleted, r1)
            n2 = r2 - bisect.bisect_left(deleted, r2)
            if n2 >= n1:
                ws.merge_cells(start_row=n1, start_column=c1, end_row=n2, end_column=c2)
    ```
    **ОБЯЗАТЕЛЬНАЯ верификация (главная защита, не код выше):** собрать множество ключей
    (артикулов/наименований) ДО и ПОСЛЕ и проверить `set(orig) - set(to_delete) == set(result)`.
    «Непрерывная нумерация» ≠ «нет потерь». Перед пакетной правкой — бэкап оригинала +
    dry-run, печатающий план (что удаляем/переименовываем). Альтернатива (надёжнее на
    очень сложных листах): вставку/удаление строк делает **пользователь в Excel** (формулы
    и merge сдвигаются корректно), Codex перечитывает структуру и заполняет данные.
    (Источник: feedback openpyxl-merged-delete-rows, vor-fix-zamechaniya.)
17. **Жёсткие `SUM`-диапазоны рвутся при вставке строк за концом блока.** Лист-сводная,
    агрегирующий рабочий лист формулами `SUM(Рабочая!X10:X50)` по блокам merged-B, при
    добавлении строк в конец блока **не растягивается** автоматически (Excel расширяет
    диапазон только при вставке ВНУТРЬ, не на границе) → итоги врут (реальный кейс:
    занижение закупки на ~27 млн). **После пополнения исходного листа — дотянуть SUM
    вручную и проверить ВСЕ колонки, не только базовые** (производные колонки — долги,
    остатки — легко пропустить; их ловит только полная сверка целостности). Отдельная
    ловушка: **агрегат-долг = `SUM(факт.долги)` по блокам, а НЕ разница `D−E`** — если в
    строках есть услуги/спецстроки, где построчный долг задан вручную или пуст, пересчёт
    через разницу даёт неверный итог. После правок openpyxl — пересчитать кэш в Excel COM
    и прогнать [[excel-validator]] (пошаговый read-back базовых колонок производные пропускает).
    (Источник: feedback svodnaya-hardcoded-ranges, upd-batch-sit-center.)

## Read-back verification после генерации (§4 Karpathy)

**Правило:** после `wb.save()` / записи через excel-mcp — открыть файл обратно и проверить ключевые признаки. Без verify-шага легко получить пустой xlsx, потерянные формулы, не те типы данных, или незакомиченные изменения в memory-объекте.

```python
import openpyxl

# 1. Запись
wb.save("output.xlsx")

# 2. Read-back verification
verify_wb = openpyxl.load_workbook("output.xlsx", data_only=False)

# Лист существует
assert sheet_name in verify_wb.sheetnames, f"Лист {sheet_name} пропал после save"
ws = verify_wb[sheet_name]

# Количество строк соответствует ожидаемому
assert ws.max_row == expected_rows, f"Ожидали {expected_rows} строк, в файле {ws.max_row}"

# Формулы сохранились (если писали формулы — data_only=False сохраняет их как строки '=...')
if expected_formulas:
    for coord, expected_formula in expected_formulas.items():
        actual = ws[coord].value
        assert actual == expected_formula, f"{coord}: ожидали {expected_formula}, получили {actual}"

# Тип данных в ключевых колонках
for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
    assert isinstance(row[0], (int, float)), f"В колонке A нечисло: {row[0]}"
```

Для критичных файлов (спецификации, реестры на сдачу) — после verify ещё спавнить агента [[excel-validator]] (формулы, дубликаты, расхождения с эталоном).

**Особый случай — формулы:** если файл создан Python и **не** открывался в Excel, `data_only=True` вернёт `None` для всех формул (нет cached значений). Read-back проверяет **строку формулы**, не результат. Для проверки результата — либо открыть руками в Excel, либо использовать `pycel`/`xlcalculator` для пересчёта.

## Когда вызывать агента excel-validator

После любой правки Excel или перед сдачей файла заказчику — спавнить subagent `excel-validator`. Он проверит формулы (нет ли #REF! / #DIV/0!), типы данных по колонкам, дубликаты, расхождения с эталоном (если эталон передан), и выдаст отчёт со списком замечаний.
