---
name: upd-parser
description: Use when УПД или накладную нужно разобрать в структуру.
---

# upd-parser — парсинг УПД от поставщиков

## Когда подключаться

Любая задача с УПД, счёт-фактурой, ТОРГ-12 где надо получить **структурированный список позиций** для дальнейшей сверки/учёта. Если просто посмотреть «что внутри» — markitdown MCP справится без скилла.

## ⚠ Ловушка из памяти

**Не делать выводов о swap'е артикулов без визуальной сверки.** PDF text-extraction (pdfplumber/pdf-mcp) не отражает линейную структуру таблицы — две колонки могут перепутаться местами в текстовом выводе. Перед тем как заявить «поставщик переименовал артикул» — обязательно отрендерить страницу в PNG и посмотреть глазами (`pdf-mcp pdf_render_pages`).

## Алгоритм

### Шаг 1 — определить тип PDF (текстовый vs скан)

Стандартная проверка из [[doc-extract]]:

```python
import pdfplumber
with pdfplumber.open(upd_path) as pdf:
    text_total = sum(len((p.extract_text() or "").strip()) for p in pdf.pages)
    n_pages = len(pdf.pages)
is_scan = text_total < 50 * n_pages
```

- **Текстовый УПД** (обычный e-документ от ЭДО) → шаг 2
- **Скан УПД** (распечатан + отсканирован) → routing на [[image-text-replace]] EasyOCR pipeline, затем шаг 2 на полученном тексте

### Шаг 2 — извлечь поля шапки

Используй helper:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".agents/skills/upd-parser/scripts"))
from parse_upd import parse_header, parse_items, parse_totals

with pdfplumber.open(upd_path) as pdf:
    full_text = "\n".join(p.extract_text() for p in pdf.pages)

header = parse_header(full_text)
# {upd_number, upd_date, seller: {name, inn, kpp}, buyer: {name, inn, kpp}, contract_ref}
```

### Шаг 3 — извлечь таблицу позиций

```python
items = parse_items(upd_path)
# [{row, code, name, unit, qty, price, amount, vat_rate, vat_amount, amount_with_vat}, ...]
```

**Важно:** для табличных данных лучше использовать `pdfplumber.extract_tables()` напрямую (с координатами), чем парсить через текст. Helper это делает.

### Шаг 4 — итоги и НДС

```python
totals = parse_totals(full_text)
# {sum_without_vat, vat_total, sum_total, vat_breakdown: {0%: ..., 10%: ..., 20%: ...}}
```

### Шаг 5 — собрать итоговый JSON и провести valid-check

```python
result = {
    "upd_number": header["upd_number"],
    "upd_date": header["upd_date"],
    "seller": header["seller"],
    "buyer": header["buyer"],  # должно совпасть с нашей организацией (ИНН <ИНН>)
    "contract_ref": header.get("contract_ref"),
    "items": items,
    "totals": totals,
    "source_file": upd_path,
    "is_scan": is_scan,
    "warnings": [],
}

# Verify: buyer = наша организация
OUR_INN = "<ИНН>"  # подставить ИНН своей организации
if result["buyer"].get("inn") != OUR_INN:
    result["warnings"].append(f"Покупатель не наша организация: ИНН {result['buyer'].get('inn')}")

# Verify: сумма items.amount = totals.sum_without_vat (с точностью до копеек)
items_sum = sum(i["amount"] for i in items if i.get("amount") is not None)
if abs(items_sum - totals["sum_without_vat"]) > 0.01:
    result["warnings"].append(
        f"Сумма позиций {items_sum} ≠ итог {totals['sum_without_vat']}"
    )
```

## Output JSON schema

```json
{
  "upd_number": "УПД-456",
  "upd_date": "2026-05-15",
  "seller": {
    "name": "ООО Поставщик-Х",
    "inn": "7712345678",
    "kpp": "771201001",
    "address": "г. Москва, ..."
  },
  "buyer": {
    "name": "ООО <организация>",
    "inn": "<ИНН>",
    "kpp": "772401001"
  },
  "contract_ref": "Договор поставки № 12 от 01.04.2026",
  "items": [
    {
      "row": 1,
      "code": "ABC-123",
      "name": "Кабель UTP 5e 4x2x0.5",
      "unit": "м",
      "qty": 1000.0,
      "price": 35.50,
      "amount": 35500.00,
      "vat_rate": "20%",
      "vat_amount": 7100.00,
      "amount_with_vat": 42600.00
    }
  ],
  "totals": {
    "sum_without_vat": 35500.00,
    "vat_total": 7100.00,
    "sum_total": 42600.00,
    "vat_breakdown": {"0%": 0, "10%": 0, "20%": 42600.00}
  },
  "source_file": "C:/.../УПД №УПД-456.pdf",
  "is_scan": false,
  "warnings": []
}
```

## Связь с другими скиллами и нашими процессами

- **Перед парсингом:** [[doc-extract]] определяет тип (текст vs скан); скан → [[image-text-replace]].
- **После парсинга — сверка со спецификацией:** загрузить нашу спец через [[excel-helper]], сверить D (артикул) и сумму с UPD items.
- **При расхождении артикула:** заменить артикул в колонке D, а в эту же ячейку добавить **красным** пометку «(Было <старый_артикул>)» — чтобы сохранить историю переименования, а не затереть её молча.
- **Обновление S/J/I/R:** НЕ перезаписывать накопленные значения, а **прибавлять** новое к существующему (история поставок сохраняется). При этом колонки S и J держать зеркальными: изменение в S отражать в J (S↔J зеркалирование), иначе расхождение между листами.

## Ошибки и graceful degradation

- Файл не существует → `{"status": "error", "reason": "file not found"}`
- Не PDF → `{"status": "error", "reason": "unsupported format, expected .pdf"}`
- Не удалось определить ИНН поставщика → возвращай частичный JSON с `"seller.inn": null`, добавь `warnings: ["seller INN not detected"]`. **Не выдумывай.**
- Не нашлась таблица позиций → `{"items": [], "warnings": ["items table not found, check PDF structure"]}`
- Скан очень плохого качества (EasyOCR confidence < 0.5 на ключевых полях) → `warnings: ["low OCR confidence on fields: ..."]`

## Ловушки

1. **Многостраничный УПД** — большая таблица может разрываться. `parse_items` обрабатывает все страницы и склеивает таблицы.
2. **Объединённые ячейки** в шапке УПД (название → 2 строки) — извлекаются как multi-line строка с `\n` внутри значения. Helper нормализует через `re.sub(r'\s+', ' ', text)`.
3. **НДС-ставка как «Без НДС»** — в `vat_rate` будет строка `"Без НДС"`, не `"0%"`. В `vat_breakdown` агрегировать в отдельный ключ или обработать.
4. **Поставщик как ИП** — может не быть КПП, только ИНН (12 цифр вместо 10). Helper это учитывает.
5. **Различия УПД-1 vs УПД-2** — УПД-2 без шапки счёт-фактуры, только накладная. Парсер не падает, просто `vat_*` поля = null.

## Контрольная сумма документа (ОБЯЗАТЕЛЬНЫЙ финал внесения первички)

После внесения позиций УПД/накладной/счёта в реестр — обязательная сверка
(ловит весь класс ошибок маппинга одной проверкой: пропуск, дубль, ошибка цены/кол-ва):

- **Σ внесённых позиций == «Всего к оплате» документа** (до копейки).
- **Число внесённых строк == число позиций документа.**
- **Все листы многостраничного скана учтены** — проверить `page_count` и фразу
  «составлен на N листах». Типичное слепое пятно: одиночная позиция на ПОСЛЕДНЕМ листе.
- **Двойники по габариту** (одинаковый размер, разное исполнение/цена) — различать по
  доп.признаку, сверять по сумме: легко отметить один и пропустить второй.

Детерминированный верификатор: `scripts/verify_document_entry.py` (диапазон строк +
эталонная сумма + N позиций → PASS/FAIL с построчной диагностикой), зависит только от
openpyxl. Прогон ловит пропуск мгновенно.

**Коэффициент НДС как cross-check.** Цены в УПД — БЕЗ НДС, в реестре закупка O — С НДС.
С 2026 ставка НДС РФ = **22%** → `цена_УПД × 1.22 = O` нужной строки. Надёжная
перекрёстная проверка сопоставления позиции скана с реестром (ловит misread артикула/
кол-ва на мелких сканах: 1↔2 в «ЩАО1.2»/«2.1»). Для позиций закупка=продажа (берут ради
срока поставки, доход 0): `цена_УПД × 1.22 = G`, а O = G. Сверять позицию И названием,
И ценой — не только глазами. (Источник: feedback upd-batch-sit-center, document-control-sum-rule.)

**Запись в живой финансовый реестр** — всегда показывать пользователю точные значения
ячеек (diff «было→станет») и получать явное «да» ДО записи.

## Когда вызывать pdf-reviewer

Если после парсинга есть `warnings` или подозрение на неправильную структуру — спавнить subagent `pdf-reviewer` для визуальной проверки страницы (отрендерит и сверит с парсингом).

## Tools (слой 3)

Папка `scripts/` содержит детерминированные скрипты скилла — это 3-й слой стандарта скиллов (Description + Instructions + **Tools**). Здесь живёт повторяемая логика, которую не нужно переписывать в каждой сессии:

- `scripts/parse_upd.py` — helper-функции `parse_header` / `parse_items` / `parse_totals` (см. Шаги 2-4). Подключается через `sys.path.insert(0, str(Path.home() / ".agents/skills/upd-parser/scripts"))`.
- `scripts/verify_document_entry.py` — контрольная сумма документа (CLI): `python verify_document_entry.py reestr.xlsx --sheet "Спец. 20" --col O --rows 244:250 --expected-sum 923750.40 --expected-count 7`. PASS/FAIL с диагностикой пропуск/дубль. Обязательный финал внесения первички (см. секцию выше). Связанный chain — `chains/upd-to-spec-reconcile.md`.
