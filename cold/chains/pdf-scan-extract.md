---
chain: pdf-scan-extract
status: active
created: 2026-05-20
triggers:
  - «разбери скан-PDF»
  - «извлеки данные из сканированного документа»
  - «прочитай скан»
  - «OCR PDF»
  - «найди значение в скане»
related_skills:
  - [[doc-extract]]
  - [[image-text-replace]]
  - [[karpathy-guidelines]]
---

# chain:pdf-scan-extract

## Назначение

Извлечение данных из сканированного PDF: определение типа
(скан vs текстовый), OCR с координатами, структурирование в JSON,
опциональная валидация значений.

## Шаги

### Stage 1 — detect (collect)

Прочитать PDF через `pdfplumber.extract_text()`. Если
text length ≈ 0 + есть images на странице → это **скан**, переход
на Stage 2 OCR. Иначе → выход из chain (текстовый PDF извлекает
skill doc-extract, pymupdf-ветка).

**Verify:** явный признак scan vs text (text length, image count)
задокументирован в выводе.

### Stage 2 — OCR (extract)

Запустить `image-text-replace` pipeline в primary OCR-режиме:
EasyOCR RU+EN, `smart_cap_height_detect` для шрифт-калибровки,
bbox normalisation. Получить список токенов с координатами.

**Verify:** OCR вернул не пустой список токенов. Если пустой —
поднять fail и эскалировать пользователю («скан низкого качества,
OCR не справился, нужен исходник).

### Stage 3 — structure (extract → JSON)

По задаче пользователя — выделить ключевые значения:

- если это таблица счёта:
  `{counterparty, inn, sum, vat, items, date}`;
- если это форма: `{field_name: value}` для каждой label→value
  пары через `find_neighbor_cell_reference`;
- иначе — список токенов с координатами как есть.

**Verify:** JSON соответствует ожидаемой схеме (поля непустые,
типы правильные, ИНН 10 или 12 цифр, суммы > 0 если применимо).

### Stage 4 — return / validate

Вернуть JSON пользователю. Если задача требует валидации (сумма > 0,
ИНН валиден, дата в разумном диапазоне) — прогнать проверки и
подсветить расхождения.

**Verify:** все обязательные поля валидны, расхождения явно указаны.

## Когда НЕ использовать

- Текстовый PDF с text layer — skill doc-extract справится
  без OCR (pymupdf).
- Растровое изображение (PNG/JPG) без PDF-обёртки → переход напрямую
  в `image-text-replace` скилл, не через chain.
- Скан низкого разрешения (< 150 dpi) — OCR даст мусор, лучше
  попросить пересканировать.
