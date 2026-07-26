# Cherry-pick batch-инструментов из prumputira/autocad-mcp v5.0

**Зачем (P0 из harvest 2026-06-04):** воссоздание плана = сотни примитивов = сотни
API-вызовов = главный bottleneck по токенам/латентности. `prumputira/autocad-mcp` v5.0
даёт `draw_*_batch` инструменты (рисовать пачкой за один вызов) → **−60-70% вызовов**.

**Почему cherry-pick, а не миграция:** `prumputira` — прямая эволюция нашей же кодовой
базы (puran-water): те же 3 бэкенда (file_ipc / COM / ezdxf), **Apache-2.0** (совместимо).
Это `git merge`/перенос модуля, а не смена сервера. Наши наработки (dyn-props, кириллица,
PDFIMPORT-калибровка) остаются.

## Шаги (на рабочем ПК с AutoCAD)

1. **Склонировать донор** (bypass proxy):
   ```powershell
   $env:HTTPS_PROXY=""; git clone https://github.com/prumputira/autocad-mcp.git C:\temp\prumputira
   ```
2. **Сверить базу:** убедиться, что структура `src/autocad_mcp/` совпадает с нашей
   (backends/, server.py). Если структура расходится — переносить не файлами, а функциями.
3. **Найти batch-инструменты:** в `server.py`/`backends/` донора — функции с `_batch`
   (напр. `draw_line_batch`, `draw_circle_batch`, `insert_block_batch`). Изучить их сигнатуры.
4. **Перенести в наш сервер:**
   - добавить batch-функции в соответствующий backend (file_ipc.py: один LISP-вызов на пачку,
     не цикл по одному — в этом весь выигрыш);
   - зарегистрировать новые tools в `server.py` (рядом с `drawing`/`entity`).
5. **Сохранить НАШИ правки:** не затирать cp1251-патч (file_ipc_cp1251.patch) и LISP-dispatch.
6. **Тест на живом AutoCAD:** нарисовать 50 линий батчем vs по одной — сверить число
   IPC-вызовов и результат скрином (PNGOUT / capture_screenshot).
7. **Вендор-снапшот:** зафиксировать получившийся сервер как наш форк (чтобы переустановка
   через setup-extras не затёрла). Обновить mcp-manifest.json: source — наш форк, не upstream zip.

## Что ещё полезного есть у prumputira (опц.)

- `excel_export` сущностей DWG — мост к нашим спецификациям/ВОР.
- 8→22 инструмента в целом — пройтись по списку, забрать релевантное recreation.

## ⚠ Риск-контроль (из harvest)

Наш COM-сценарий держится на `execute_lisp` (README puran-water заявляет LT без COM).
Регресс upstream опасен → **держать вендор-снапшот + тесты COM-пути**. Cherry-pick из
prumputira (Apache, общая база) предпочтительнее слепого `git pull` upstream puran-water.

Источник: `session-reports/2026-06-04_autocad-mcp-harvest/report.md`.
