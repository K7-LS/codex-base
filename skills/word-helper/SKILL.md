---
name: word-helper
description: Use when нужно прочитать, изменить или проверить DOCX.
---

# word-helper

## Когда подключаться

Любая задача с `.docx`/`.doc`, выходящая за «открой и покажи». Если просто прочитать абзац — markitdown MCP справится без скилла.

## Иерархия инструментов

| Задача | Инструмент | Заметка |
|--------|------------|---------|
| Превью в Markdown | `markitdown-mcp` | Лучший общий читатель |
| CRUD абзацев, find-replace, стили | `word` MCP (office-word-mcp-server) | Прямая правка docx |
| Сложная правка структуры | Python `python-docx` | Низкоуровнево, но гибко |
| Сохранить форматирование при чтении | Python `mammoth` (docx → html) | mammoth честнее для inline-стилей |
| Генерация по шаблону | Python `python-docx-template` (docxtpl) | Jinja2 syntax внутри docx |
| Экспорт в PDF | LibreOffice headless / Word COM (если установлен) / `docx2pdf` | Без Office нет 100% точного PDF |

## Оформление — нейтральное, БЕЗ синего Codex-стиля

**Мы серьёзная компания.** НЕ применять декоративный синий стиль к деловым docx
(синие заголовки, синяя заливка таблиц типа «Light List Accent 1», цветной текст).
По умолчанию:

- **Заголовки/текст** — чёрные, стили документа/шаблона, без акцентных цветов.
- **Таблицы** — простая сетка («Table Grid») или стиль шаблона, без цветных шапок.
  НЕ `Accent`/цветные built-in стили.
- **При правке существующего** — наследовать стили документа, НЕ навязывать свой.
- **Никаких брендовых LLM-палитр** на клиентских документах.
- **Цвет ТОЛЬКО** если есть в источнике или попросил пользователь.

## Правка СУЩЕСТВУЮЩЕГО docx с шапкой/полями — хирургический native custom agent plan

> Грунт под реальным провалом 2026-06-01 (3-4 кривых сдачи с «готово, проверено»).
> Полный разбор: `~/.codex/base/cold/memory/reference_docx_editing_failures.md`.

Генерация **с нуля** обычно ок. Боль — правка **готового** файла со стилями/шапкой/
полями. Правила (нарушение = «ломает, переворачивает, underline сбивает»):

1. **СНАЧАЛА дамп структуры**, НЕ заполнять вслепую: `doc.sections`, header/footer,
   якоря `w:drawing`, индексы **всех** таблиц, стили. Понять материал → потом метод.
2. **Не пересобирать с нуля** (выбросит фирменную шапку/логотип). Править оригинал.
3. **Плавающую шапку/логотип** (`w:drawing`, заякорен) python-docx ломает при нарезке →
   логотип уплывает. Проще **убить и поставить inline-блоком в самый ВЕРХ** (таблица
   2 кол.: логотип | название, без границ). Логотип — настоящий из `word/media/imageN.*`.
4. **НЕ трогать табы и подчёркивания** полей «(ФИО)/(подпись)». Точечная замена
   ЗНАЧЕНИЯ внутри run, НЕ переписывать абзац целиком (это разносит выравнивание).
5. **Пустые абзацы** (пачки 9-28 после подписей) выталкивают подвал на лишние страницы.
6. **Кириллический путь:** скрипт через Write-tool (UTF-8); файл искать `os.listdir()`
   по ASCII-подстроке / `Get-ChildItem -Filter '*_02.docx'`; НЕ кириллица в bash-арг.
7. **VERIFY-ГЕЙТ обязателен:** каждый «готово» = **PDF-рендер постранично + взгляд
   глазами** + read-back + агент `word-checker`. Никаких «проверено» на веру.

Опциональный assist (не обязателен): `docx-plus` (style-cascade под «underline плывёт»),
`OfficeIMO` (.NET, зрелый). Валидировать перед внедрением. См. memory-файл выше.

## Типовые задачи

### Find-and-replace по всему документу

```python
from docx import Document
doc = Document("input.docx")

replacements = {
    "{{ИМЯ}}": "<ФИО>",
    "{{ДАТА}}": "07.05.2026",
}

# Ловушка: текст может быть разорван на несколько runs внутри одного paragraph
# (Word делит при stylе-changes). Пройтись по runs наивно — пропустит совпадения.
# Простой надёжный способ:
for para in doc.paragraphs:
    full = para.text
    for old, new in replacements.items():
        if old in full:
            full = full.replace(old, new)
    if full != para.text:
        # Очистить runs и записать новый текст единым run'ом (теряется in-paragraph
        # форматирование — приемлемый trade-off ТОЛЬКО для простых шаблонов).
        # ⚠ ОПАСНО для бланков с табами/подчёркиваниями/выровненными полями
        # (ФИО)/(подпись): этот паттерн разносит выравнивание. Там — точечная
        # замена внутри нужного run, см. секцию «Правка существующего docx».
        for run in para.runs[1:]:
            run.text = ""
        para.runs[0].text = full

# То же для таблиц
for table in doc.tables:
    for row in table.rows:
        for cell in row.cells:
            for para in cell.paragraphs:
                pass  # повторить логику выше

doc.save("output.docx")
```

Для шаблонной генерации с Jinja2-like синтаксисом проще `docxtpl`:

```python
from docxtpl import DocxTemplate
tpl = DocxTemplate("template.docx")
tpl.render({"name": "<ФИО>", "date": "07.05.2026"})
tpl.save("filled.docx")
```

### Извлечение структуры (заголовки, оглавление)

```python
from docx import Document
doc = Document("input.docx")
for para in doc.paragraphs:
    if para.style.name.startswith("Heading"):
        level = para.style.name.replace("Heading ", "")
        print(f"{'  ' * (int(level) - 1)}{para.text}")
```

### Слияние нескольких docx в один

```python
from docxcompose.composer import Composer
from docx import Document
master = Document("main.docx")
composer = Composer(master)
for f in ["chapter2.docx", "chapter3.docx"]:
    composer.append(Document(f))
composer.save("combined.docx")
```

(требует пакет `docxcompose`)

### Конвертация в Markdown

Через MCP markitdown — Codex вызовет сам. Через Python:

```python
import mammoth
with open("input.docx", "rb") as f:
    result = mammoth.convert_to_markdown(f)
    print(result.value)
```

### Конвертация в PDF (без Office на машине)

```bash
# LibreOffice headless (нужно установить LibreOffice)
soffice --headless --convert-to pdf input.docx
```

Без LibreOffice / Word — на чистой машине нет надёжного пути из Python. Скажи пользователю установить LibreOffice (User-installer без админа) или открыть файл в Word и сохранить как PDF вручную.

## Ловушки

1. **Разорванный `<w:t>`** — Word делит текст внутри параграфа на несколько `runs` при изменении стилей внутри предложения. Find-replace по `run.text` пропустит совпадения. Решение: операция на уровне `paragraph.text`, потом перезапись runs (см. пример выше). Минус — теряется in-paragraph форматирование.
2. **Шрифты** — если в шаблоне используется PT Astra Sans / GOST шрифт, при генерации на чужой машине без шрифта Word подменит на похожий и сместит верстку. На пользовательском ПК ставить нужные шрифты заранее.
3. **Таблицы со сложной разметкой** — `python-docx` теряет некоторые свойства cell width / borders при правке. Для табличных шаблонов лучше использовать docxtpl или править через Word MCP.
4. **Стили (Heading 1, Heading 2)** — должны существовать в документе ДО присвоения параграфу. Иначе AttributeError. Создавать через `doc.styles.add_style()` если их нет.
5. **Сохранение в .doc (старый формат)** — `python-docx` НЕ умеет, только .docx. Для .doc — конвертировать через LibreOffice headless.
6. **Раздельные секции (sections)** — для верстки альбомных листов или разных колонтитулов. python-docx работает с ними через `doc.sections`.
7. **Списки и нумерация** — глубокий enchant: `numbering.xml` в docx определяет нумерацию, на одном файле может быть несколько определений. Простая правка через python-docx может не взлететь.
8. **⚠ ЧТЕНИЕ таблиц: merged-ячейка считается N раз** — `row.cells` (python-docx) возвращает
   объединённую ячейку по разу на КАЖДЫЙ grid-слот (`gridSpan`/`vMerge`); word-MCP наследует то же.
   Суммирование «в лоб» по ячейкам удваивает цену, стоящую на 2 позиции (реальный кейс 2026-06:
   двойной счёт, модель настаивала «ошибки нет»). Перед агрегацией — дедупликация по identity
   XML-элемента:
   ```python
   seen, uniq = set(), []
   for cell in row.cells:
       if id(cell._tc) not in seen:
           seen.add(id(cell._tc)); uniq.append(cell)
   ```
   Любую сумму из docx-таблицы подтверждать независимым пересчётом по уникальным ячейкам.
   ⚠ Дедуп корректен, только пока держишь ссылки на ячейки (`uniq.append(cell)`), как в
   сниппете выше. «Голый» `seen.add(id(cell._tc))` БЕЗ удержания ссылки — ловушка наоборот:
   lxml-прокси эфемерен, GC его освобождает, id переиспользуется прокси СЛЕДУЮЩЕЙ ячейки →
   живые ячейки ложно отсеиваются как «дубли» (реальный кейс 2026-07-11: read-back-верификация
   «теряла» заполненные строки таблицы, файл при этом был цел). Для проверки НАЛИЧИЯ подстрок
   (read-back verify) дедуп не нужен вовсе — дубли безвредны, читай все ячейки подряд.
9. **⚠ `capability `document.word.read`` ДУБЛИРУЕТ текст в таблицах** (anti-patterns A3.8). На ячейке с `gridSpan`/merge рапортует «N occurrences» и вставляет replace N× в один run → задвоение, документ испорчен. **Акт ИД = одна таблица — особо опасно.** НЕ использовать для текста внутри таблиц. Надёжный путь — in-place правка `word/document.xml` через ZipArchive:
   ```powershell
   Add-Type -AssemblyName System.IO.Compression
   $zip = [IO.Compression.ZipFile]::Open($docx,'Update'); $e=$zip.GetEntry('word/document.xml')
   $r=New-Object IO.StreamReader($e.Open(),[Text.Encoding]::UTF8); $xml=$r.ReadToEnd(); $r.Dispose()
   if (([regex]::Matches($xml,[regex]::Escape($find))).Count -eq 1){   # count ДО замены!
       $xml=$xml.Replace($find,$replace)
       $s=$e.Open(); $s.SetLength(0)
       $w=New-Object IO.StreamWriter($s,(New-Object Text.UTF8Encoding($false)))  # UTF-8 без BOM
       $w.Write($xml); $w.Dispose() }
   $zip.Dispose()
   ```
   Целиться в **целый run** (`<w:t>…</w:t>`); cross-run фрагмент `.Replace` не возьмёт. Бэкап до правки. (Источник: акты ИД, <шифр> 2026-06-05.)
9. **Метаданные python-docx** — новый docx получает `author: python-docx`, `created/modified: 2013-12-23` (артефакт библиотеки). Перед сдачей заполнять `core_properties` (author/title/created) или хотя бы знать, что дата 2013 — не баг данных. (Источник: collaborative-excel-tools, ПНР-серия.)

## Read-back verification после генерации (§4 Karpathy)

**Правило:** после любой генерации/правки `.docx` — прочитать обратно ключевые признаки и проверить. Без verify-шага «сгенерировал и забыл» = почти гарантированный мусор: незаменённые `{{placeholder}}`, пустые runs, потерянные стили.

```python
from docx import Document

# 1. Генерация
doc.save("output.docx")

# 2. Read-back verification
verify = Document("output.docx")
paragraphs = [p.text for p in verify.paragraphs]
text_full = "\n".join(paragraphs)

# Проверки:
import re
unfilled = re.findall(r"\{\{[^}]+\}\}", text_full)
if unfilled:
    raise RuntimeError(f"Незаменённые плейсхолдеры: {set(unfilled)}")

if not paragraphs or all(not p.strip() for p in paragraphs):
    raise RuntimeError("Документ пустой после сохранения")

# Опционально: ожидаемые подстановки реально появились
for key, value in expected_values.items():
    if value not in text_full:
        raise RuntimeError(f"Значение {key}='{value}' не найдено в выводе")
```

Для критичных шаблонов (фирменные письма <организация>, претензии, договоры) — после verify ещё спавнить агента [[word-checker]].

## Корпоративные шаблоны

Публичная база не содержит фирменный бланк, реквизиты или персональные данные
организации. Для делового письма пользователь должен передать конкретный
шаблон проекта. Сначала прочитать его структуру и реальные плейсхолдеры,
сохранить оригинал и работать с копией. Если шаблон не предоставлен — вернуть
`BLOCKED`, а не выдумывать реквизиты или скрытый путь.

## Когда вызывать агента word-checker

После генерации документа (особенно по шаблону) — спавнить subagent `word-checker`. Он проверит структуру (заголовки, оглавление), таблицы (на повреждения после правки), наличие placeholder'ов которые не заменились (`{{...}}`), форматирование. Выдаст отчёт со списком замечаний.
