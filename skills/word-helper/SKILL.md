---
name: word-helper
description: Use when нужно прочитать, изменить или проверить DOCX.
---

# word-helper

## Когда подключаться

Задача с `.docx`/`.doc`, требующая чтения, правки или проверки структуры.
Простой абзац прочитай уже доступным средством без отдельного workflow.

## Иерархия инструментов

Сначала сопоставь нужные операции реальным tools и зависимостям host.
Ни один provider из таблицы не гарантирован поставкой базы. Проверенный
OfficeCLI также допустим по фактической операции; не устанавливай и не обновляй
его компоненты автоматически. Чтение, запись и рендер проверяются отдельно.

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

## Правка готового бланка с шапкой и полями

> Основание — повторные ошибки правки бланка 2026-06-01.
> Полный разбор: `~/.codex/base/cold/memory/reference_docx_editing_failures.md`.

Генерация **с нуля** обычно ок. Боль — правка **готового** файла со стилями/шапкой/
полями. Правила (нарушение = «ломает, переворачивает, underline сбивает»):

1. **СНАЧАЛА дамп структуры**, НЕ заполнять вслепую: `doc.sections`, header/footer,
   якоря `w:drawing`, индексы **всех** таблиц, стили. Понять материал → потом метод.
2. **Не пересобирать с нуля** (можно потерять фирменную шапку/логотип).
   Сохранить исходник, точечно править копию в разрешённом каталоге.
3. **Плавающую шапку/логотип** сохранить вместе с anchor, media и relationships.
   Перестройка абзаца с `w:drawing` может удалить или сдвинуть рисунок; менять только
   нужные текстовые узлы. Перевод в inline меняет композицию бланка и требует
   решения пользователя, если это изменение не входило в задание.
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

### Точечная замена в простом текстовом абзаце

Пример ниже работает с XML-элементом `w:p` и сохраняет существующие runs и их
свойства. Новое значение получает стиль первого затронутого run; окружающий
текст сохраняет свои стили. Это не готовая замена по всему DOCX: область надо
выбрать по карте полей, а колонтитулы и таблицы проверить отдельно.
Абзацы с табами, рисунками, полями, ссылками и другой нетекстовой структурой
пример отклоняет до записи. Для них выбрать точечный метод в Word/OOXML,
который сохраняет эту структуру; не обходить отказ удалением узлов.
Значения с переносами строк или табами требуют отдельной обработки `w:br` /
`w:tab`; этот текстовый пример их не создаёт.

```python
def replace_text_only_paragraph(paragraph, old, new):
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    if not old:
        raise ValueError("Пустой искомый текст")
    if any(char in new for char in "\r\n\t"):
        raise ValueError("Переносы и табы требуют структурной вставки")
    if paragraph.tag != w + "p":
        raise ValueError("Ожидался выбранный абзац w:p")
    nodes = []
    for child in paragraph:
        if child.tag == w + "pPr":
            continue
        if child.tag != w + "r":
            raise ValueError("Сложная структура: нужен другой точечный метод")
        if any(n.tag not in (w + "rPr", w + "t") for n in child):
            raise ValueError("Нетекстовые узлы: пример неприменим")
        nodes.extend(n for n in child if n.tag == w + "t")
    full = "".join(n.text or "" for n in nodes)
    start = full.find(old)
    if start < 0:
        return 0
    if full.find(old, start + 1) >= 0:
        raise ValueError("Несколько совпадений: сначала уточнить область замены")
    end = start + len(old)
    offset = 0
    for node in nodes:
        text = node.text or ""
        next_offset = offset + len(text)
        if next_offset > start and offset < end:
            prefix = text[:max(0, start - offset)]
            suffix = text[max(0, end - offset):]
            value = new if offset <= start < next_offset else ""
            node.text = prefix + value + suffix
            if node.text[:1].isspace() or node.text[-1:].isspace():
                node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        offset = next_offset
    return 1
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

Через доступный MCP markitdown либо установленный Python-пакет:

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

Если доступного проверенного рендера нет, оставь визуальную приёмку открытой
и назови конкретную возможность для её выполнения. Установка нового ПО
требует разрешения; наличие Python само по себе не подтверждает точный рендер.

## Ловушки

1. **Разорванный `<w:t>`** — Word делит текст на несколько runs. Поиск по одному
   `run.text` пропускает такое совпадение. Сопоставить текст с границами исходных
   узлов и заменить только затронутый диапазон; см. ограниченный пример выше.
   Присвоение `paragraph.text` или очистка остальных runs теряют форматирование
   и нетекстовую структуру, поэтому не подходят для сохранения готового бланка.
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
9. **Повторная замена в merged-ячейке.** В историческом случае операция массового
   find/replace обходила одну XML-ячейку несколько раз и вставляла текст повторно
   (anti-patterns A3.8; акты ИД, 2026-06-05). Точное имя и версия инструмента здесь
   не сохранены: это не дефект capability `document.word.read` и не запрет чтения.
   До записи проверить поведение выбранного редактора на копии; после — число
   замен и текст уникальных ячеек. Для одной точно найденной XML-подстроки возможна
   правка `word/document.xml` в копии через ZipArchive:
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
   Это узкий пример: `$find` и `$replace` — заранее проверенные XML-фрагменты
   с корректным экранированием; `w:t` — текстовый узел внутри run. Ноль или несколько
   совпадений означают, что замена не выполнена; не объявлять успех. Cross-run
   фрагмент `.Replace` не возьмёт. Бэкап до правки, разбор XML и read-back после неё.
10. **Метаданные python-docx** — новый docx получает `author: python-docx`, `created/modified: 2013-12-23` (артефакт библиотеки). Перед сдачей заполнять `core_properties` (author/title/created) или хотя бы знать, что дата 2013 — не баг данных. (Источник: collaborative-excel-tools, ПНР-серия.)

## Read-back verification после генерации (§4 Karpathy)

**Правило:** после любой генерации/правки `.docx` — прочитать обратно ключевые признаки и проверить. Без verify-шага «сгенерировал и забыл» = почти гарантированный мусор: незаменённые `{{placeholder}}`, пустые runs, потерянные стили.

```python
from docx import Document
from docx.oxml.ns import qn

# 1. Генерация
doc.save("output.docx")

# 2. Read-back verification
verify = Document("output.docx")
parts = [verify._element]
for section in verify.sections:
    parts.extend(part._element for part in (
        section.header, section.first_page_header, section.even_page_header,
        section.footer, section.first_page_footer, section.even_page_footer))
# Включает таблицы/вложенные абзацы и колонтитулы; объединяет разорванные w:t.
paragraphs = ["".join(t.text or "" for t in p.iter(qn("w:t")))
              for part in parts for p in part.iter(qn("w:p"))]
text_full = "\n".join(paragraphs)

# Проверки:
import re
possible_unfilled = re.findall(r"\{\{[^}]+\}\}|\[\[[^]]+\]\]", text_full)
# Это кандидаты для сверки с картой целевых полей, не безусловный отказ:
# буквальная строка {{name}} может быть частью неизменяемого текста.

if not paragraphs or all(not p.strip() for p in paragraphs):
    raise RuntimeError("Документ пустой после сохранения")

# Опционально: ожидаемые подстановки реально появились
for key, value in expected_values.items():  # ожидаемые отображаемые строки
    if value not in text_full:
        raise RuntimeError(f"Значение {key}='{value}' не найдено в выводе")
```

Пример проверяет наличие текста, не его правильное расположение или вёрстку.
Дополнительно сверить каждое целевое поле с картой подстановок; буквальные скобки
шаблона не считать незаполненным полем. Сноски и другие части вне перечисленных
областей проверять отдельно, если они участвуют в задании. После read-back —
предусмотренные AGENTS.md проверки `word-checker`, источников и конечного рендера.

## Корпоративные шаблоны

Публичная база не содержит фирменный бланк, реквизиты или персональные данные
организации. Для делового письма пользователь должен передать конкретный
шаблон проекта. Сначала прочитать его структуру и реальные плейсхолдеры,
сохранить оригинал и работать с копией. Если шаблон не предоставлен — вернуть
`BLOCKED`, а не выдумывать реквизиты или скрытый путь.

## Когда вызывать агента word-checker

После генерации документа (особенно по шаблону) — спавнить subagent `word-checker`. Он проверит структуру (заголовки, оглавление), таблицы (на повреждения после правки), наличие placeholder'ов которые не заменились (`{{...}}`), форматирование. Выдаст отчёт со списком замечаний.
