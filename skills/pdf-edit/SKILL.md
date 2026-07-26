---
name: pdf-edit
description: Use when нужно изменить страницы, формы или аннотации PDF.
---

# pdf-edit

## Когда подключаться

Любая задача, где PDF нужно **ИЗМЕНИТЬ**: собрать/разобрать, поправить страницы,
заполнить форму, перекрасить аннотации, наложить watermark, отредактировать
вектор-чертёж.

**Разграничение (соседи):**
- **Извлечь текст/таблицы из PDF** (в т.ч. определить скан-или-текст, OCR) →
  skill `doc-extract` — единственный вход извлечения, маршрутизирует по типу листа.
- **OCR скана со структурой / замена текста НА скане-картинке** → skill `image-text-replace`.
- **Сверка/diff таблиц СО (спецификаций) по содержимому** → skill `co-verify`.
- **Проверить PDF как файл после правки** → агент `pdf-reviewer` (read-only ревьюер).

## Редактирование вектор-PDF (удалить / подвинуть штамп / объекты) — Inkscape

**Это рабочая замена провалившимся методам.** Удалять объекты, двигать текст/линии,
убирать штамп в векторном чертеже-PDF — **через Inkscape**, НЕ через белые заливки и
НЕ через content-stream surgery (PyMuPDF redact / pikepdf clip — провалено, прячет а
не удаляет, см. `anti-patterns.md` §A3.5).

**ВЕРИФИЦИРОВАНО 2026-06-02** на реальном чертеже <организация> (чистое удаление штампа,
0 растеризации, чертёж цел). Полный метод + ловушки + caveat'ы:
см. `~/.codex/base/cold/memory/reference_inkscape_pdf_editing.md`.

Кратко:
1. Открыть PDF → вкладка **«Внутренний импорт»** (не Cairo — Cairo делает текст кривыми).
2. Плотный чертёж виснет на `all` → импорт **по одной странице**.
3. Выделить (двойной клик внутрь групп / `Ctrl+Shift+G`) → `Delete` / перетащить.
4. **Сохранить как → PDF** в НОВЫЙ файл. Предупреждение «потеря данных → SVG?» = норма, жмём PDF.
5. **Проверить объективно**: `pdf_render_pages` до/после + `pdf_info` (`pages_with_raster_images`
   должно остаться 0; размер не взлетел; дельта текста = только удалённое). Не верить «на глаз».

⚠ **Производительность:** Inkscape медленно открывает/сохраняет большие чертежи (особенно
слабый ноут без GPU) — учитывать на томах. Батч (CLI `inkex`) — будущая работа.
Лицензия GPL-3.0 → только как внешняя программа, код не копировать.

## Перерисовать НАНЕСЁННУЮ графику на AutoCAD-PDF (разметка CCTV/СС/ЭО)

**Другая задача, чем Inkscape-удаление штампа.** Здесь чертёж пришёл **только в PDF**
(печать из AutoCAD, `pdfplotNN.hdi`, вектор), поверх плана — халтурная разметка
(толстые красные лучи/кружки/квадраты видеонаблюдения и т.п.), которую нужно
**перерисовать** (тонкие синие секторы, значки камер с разворотом), подложку не трогать.

**ВЕРИФИЦИРОВАНО 2026-06-03** (заказчик доволен). Два пути — выбор по тому, нужен ли DWG:

| Нужен на выходе | Метод | Memory |
|---|---|---|
| Только PDF (DWG не нужен) | **Чистый PyMuPDF через SVG-слой**, без AutoCAD — легче | [[reference_autocad_pdf_svg_markup]] |
| DWG (правка возвращается в чертёж) | **autocad-mcp** (PDFIMPORT + entmake + vla-PlotToFile) | [[reference_autocad_pdf_overlay_mcp]] |

Ключевое (общее для обоих): **content-stream surgery и redaction — тупики** (§A3.5):
толстая линия = пучок тонких `0 w` штрихов (поиск по толщине = 0 совпадений), цвет
нанесённого = родному красному плана (по цвету не отделить), redaction сносит базу.
Рабочий приём — маска нанесённого из `get_drawings()` по **цвет+толщина в page-space**,
затем либо удаление SVG-узлов (lxml) + новый слой, либо построение заново в AutoCAD.
Полные методы, геометрия камер и ловушки — в memory-файлах выше.
Мета чертежа для этих работ (штамп, текстовые блоки с bbox, слои) — извлекается
инструментом `doc-extract`: `skills/doc-extract/tools/extract_drawing_meta.py`
(+ справка `skills/doc-extract/references/drawings.md`).

## Иерархия инструментов

| Задача | Инструмент | Заметка |
|--------|------------|---------|
| Метаданные, страницы, закладки | Python `pikepdf` | Стабильно работает с большими PDF |
| Слияние/разделение, перекомпоновка | Python `pypdf` | Простой API, не теряет аннотации |
| Заполнение AcroForm | Python `pypdf.PdfWriter.update_page_form_field_values()` | XFA-формы — отдельная история, обычно не поддерживается |
| Аннотации (облачка, маркеры) | Python `pikepdf` (низкоуровневые объекты PDF) | Удалять `/AP` после смены цвета — иначе старый рендер останется |
| Сравнение двух версий PDF | рендер PNG + perceptual hash / vision | Бинарный diff бесполезен; текстовый diff таблиц СО → skill `co-verify` |
| Редактирование (merge/split/delete/rotate/extract/replace/watermark) | (нет MCP) | pikepdf + pypdf + reportlab напрямую, см. ниже |

**Правило**: всегда сначала смотри, есть ли подходящий MCP в `Codex mcp list`. Если есть — через него. Если нужна более тонкая операция — Python.

## Типовые задачи

### Объединение нескольких PDF

```python
from pypdf import PdfWriter
writer = PdfWriter()
for f in ["a.pdf", "b.pdf", "c.pdf"]:
    writer.append(f)
writer.write("combined.pdf")
writer.close()
```

### Замена/удаление страницы

```python
from pypdf import PdfReader, PdfWriter
src = PdfReader("input.pdf")
out = PdfWriter()
for i, page in enumerate(src.pages):
    if i == 4:        # пропустить 5-ю (0-based)
        continue
    out.add_page(page)
out.write("output.pdf")
```

### Заполнение AcroForm

```python
from pypdf import PdfReader, PdfWriter
reader = PdfReader("template.pdf")
writer = PdfWriter(clone_from=reader)
writer.update_page_form_field_values(
    writer.pages[0],
    {"FullName": "Иванов И.И.", "Date": "07.05.2026"}
)
writer.write("filled.pdf")
```

### Перекраска аннотаций (например, облачка)

```python
import pikepdf
pdf = pikepdf.open("input.pdf")
for page in pdf.pages:
    for annot in page.get("/Annots", []):
        if annot.get("/Subtype") == "/PolygonCloud":
            annot["/C"]  = [1, 0, 0]    # красный border
            annot["/IC"] = [1, 0, 0]    # красная заливка
            if "/AP" in annot:
                del annot["/AP"]         # ВАЖНО: удалить cached appearance
pdf.save("output.pdf")
```

## Ловушки

1. **Reportlab + Unicode sub/super дают чёрные квадраты.** Никогда не использовать символы `₀₁₂₃₄₅₆₇₈₉`/`⁰¹²³⁴⁵⁶⁷⁸⁹` в reportlab PDF — built-in шрифты их не содержат, на месте рендерится solid black. Использовать XML-теги в Paragraph: `Paragraph("H<sub>2</sub>O", styles['Normal'])`, `Paragraph("x<super>2</super>", styles['Normal'])`. Для canvas-текста — менять размер/позицию шрифта вручную.
2. **Большие PDF (>50 МБ)** — `pymupdf` (fitz) часто падает на сложной структуре или ест 4+ ГБ RAM. Использовать связку `pikepdf` (низкоуровневая работа) + `pypdf` (комбинаторика страниц).
3. **`/AP` в аннотациях** — это закэшированный рендер. После изменения цвета или текста обязательно удалить, иначе PDF-вьюер покажет старое.
4. **Сравнение «что изменилось» между двумя PDF** — бинарный diff бесполезен. Лучший путь: отрендерить страницы в PNG (`pdftoppm`) и сравнить через perceptual hash (imagehash) или multimodal vision.
5. **Шрифты при редактировании** — если меняешь текст в PDF и нужный шрифт не embedded, текст потеряется. Проверять через `reader.metadata` или `pikepdf` perms.
6. **Сжатие при сохранении** — `pikepdf.save()` по умолчанию пересжимает. Для минимальных правок передать `linearize=True` или ничего, а вот `compress_streams=False` сохранит исходные потоки.
7. **«PDF file not found» при живом файле с «ё»/«й» в имени** — NFD-имя из внешнего источника: модель печатает NFC, NTFS не нормализует. Обход: wildcard-копия под ASCII-имя / `os.listdir`-матчинг с `unicodedata.normalize`. Полное описание — skill `doc-extract` («Ловушки извлечения») и anti-patterns A3.10.

Ловушки ИЗВЛЕЧЕНИЯ (сдвиг колонок таблиц, CID/Distiller-шрифты, скан без текст-слоя) —
переехали в skill `doc-extract`.

## Когда вызывать агента pdf-reviewer

После любой существенной правки PDF (удалили страницы, добавили аннотации, изменили формы) — спавнить subagent `pdf-reviewer` с задачей «проверь итоговый PDF на сохранность структуры». Агент сам проверит количество страниц, метаданные, целостность аннотаций, выдаст отчёт.

## Визуальный diff двух PDF

⚠ **Портативный `diff-pdf.exe` НЕ установлен** в `~/.codex/base/bin/` (раньше ожидался в
`bin/diff-pdf/` — каталога нет). Пока бинарь не доставлен вручную, визуальный diff делаем
**рендером страниц в PNG + сравнением** (это и есть рабочий путь по умолчанию, см. «Ловушки» п.4):

```python
# Рендер обеих версий и сравнение через perceptual hash / multimodal vision
import fitz  # PyMuPDF
for v in ("v1.pdf", "v2.pdf"):
    doc = fitz.open(v)
    for i, page in enumerate(doc):
        page.get_pixmap(dpi=150).save(f"{v}_p{i}.png")
# далее imagehash.phash() попарно или показать страницы vision-модели
```

Если позже доставите портативный `diff-pdf.exe` (GPL-2.0, допустим как **внешний бинарь**
через subprocess, **код не копировать**): `& diff-pdf.exe v1.pdf v2.pdf` даёт exit 0 (идентичны)
/ 1 (отличаются), флаг `--output-diff=diff.pdf` пишет наложение красным.

## Редактирование PDF — pikepdf/pypdf напрямую

Базовые операции делаем через Python-библиотеки в Bash subprocess (не своим MCP):

| Операция | Библиотека | Пример |
|----------|------------|--------|
| Merge | `pypdf.PdfWriter` + `add_page` | `for p in pages: writer.add_page(p)` |
| Split | `pikepdf.Pdf` slice | `pdf.pages[start:end]` |
| Delete pages | `del pdf.pages[idx]` | pikepdf |
| Rotate | `pdf.pages[i].rotate(90)` | pikepdf |
| Extract range | `pdf.pages[start:end]` | pikepdf |
| Replace page | `pdf.pages[i] = src.pages[j]` | pikepdf |
| Watermark text | `reportlab` → canvas → merge | через PdfWriter overlay |
| Watermark image | `reportlab.platypus.Image` | overlay |
| AcroForm fill | `pypdf.update_page_form_field_values` | pypdf |
| Аннотации | pikepdf низкоуровневый | прямая правка `/Annots` |

## MCP-роутинг

| Задача | MCP server | Скилл fallback |
|--------|------------|----------------|
| Извлечение текста/таблиц | — | **skill `doc-extract`** (единственный вход) |
| Редактирование (merge/split/rotate/watermark) | (нет MCP) | pikepdf + pypdf + reportlab |
| AcroForm заполнение | (нет MCP) | pypdf.update_page_form_field_values |
| Аннотации (перекрашивание) | (нет MCP) | pikepdf низкоуровневый |
| Визуальный diff | (нет MCP) | рендер PNG + perceptual hash / vision (diff-pdf.exe не установлен) |

## История

До 2026-07-02 скилл назывался `pdf-helper` и совмещал извлечение + редактирование.
Extraction-зона (проверка скан/текст, OCR-routing, извлечение таблиц, режим чертежей,
`extract_drawing_meta.py`) вырезана в `doc-extract` (Блок 3 реворка базы, унификация
входа извлечения). Здесь осталось только редактирование.
