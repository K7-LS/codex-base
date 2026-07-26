---
name: revit-family-generator-ru
description: Use when семейство Revit нужно собрать в RU/мм-профиле.
---

# revit-family-generator-ru — генератор семейств на нашем конвейере

Тонкая обёртка над модулем `famfab/gen` (проект «Revit шаблон наш»). Скилл НЕ дублирует
знания — он их читает из файлов-домов и ведёт по процессу. «Готово» = зелёный АВТОГЕЙТ,
не «операции выполнились».

## Дома знаний (Required reading — читать ПЕРЕД генерацией)

Корень проекта = папка, содержащая `Codex/famfab/gen/` (пути на устройствах разные,
искать от cwd; обычно сессия уже в корне проекта).

| Файл (от корня проекта) | Что там |
|---|---|
| `Codex/famfab/gen/gen_schema.md` | диалект v2: принципы, секции, ловушки схемы/валидатора/runtime, решения владельца, замечания BIM-менеджера → механизмы |
| `Codex/famfab/gen/gen_schema.json` | машинная JSON Schema (draft-07) — истина по полям |
| `Codex/famfab/gen/gen_templates.json` | справочник категория RU → шаблон .rft (override — поле `family.template`) |
| `Codex/famfab/gen/smoke/*.json` | эталонные примеры v2: `cube_v2` (extrusion+void+toggle), `tube_v2` (revolve+lookup+duct-коннекторы), `host_pat_v2`+`nest_pat_v2` (вложения+каскады) |

## Флоу (шаги строго по порядку)

1. **Референс-first.** Задача на форму реального изделия → найти РЕАЛЬНОЕ фото/чертёж
   (поиск изображений, каталог производителя, приложенный файл) и СВЕРИТЬ с владельцем:
   «это то, что нужно?» — ДО любого моделирования. Домысел формы запрещён.
2. **Вопросы владельцу** (мало и по делу, см. чек-лист): габариты/паспортные данные
   производителя (D/L/масса — из каталога, не из головы), типоразмеры (каталог? lookup?),
   категория Revit, что должно считаться в спеке, MEP-коннекторы (тип системы, откуда
   диаметр), instance/type.
3. **Чек-лист «сути семейства»** — заполнить `tools/checklist_suti_semeystva.md`
   (копией в рабочую папку задачи) ДО генерации JSON. Ключевое: каждый параметр —
   паспортный (каталог/lookup, имя из паспорта производителя) или производный
   (формула + строка в `gate.derived`); derived решается ЗДЕСЬ, не после.
4. **JSON v2** по `gen_schema.json`: секции в порядке сборки (family → reference_planes →
   dimensions → parameters → type_catalog/lookup → geometry → connectors → nested →
   controls → gate). Ожидания гейта — в том же JSON: `expected_clusters`, `bbox_terms`,
   `flex_params`, `nominal_mm`, `derived`, `connectors`, `type_name`, `flex_mode`.
5. **Валидатор офлайн** (CPython, без Revit):
   `python "<корень>/Codex/famfab/gen/gen_validate.py" <family.json>` →
   добиться 0 FAIL; каждый WARN — осознанно принять или починить.
6. **Деплой на стейдж** (ASCII-пути, ловушка №40): прогнать ОБА скрипта —
   `Codex/famfab/gen/deploy.ps1` И `Codex/famfab/verify/deploy.ps1`
   (правка verify без его деплоя — известная грабля). JSON семейства положить в
   `C:\rvt_stage\gen\smoke\` (deploy копирует из `gen/smoke/`) или напрямую.
7. **Раннер**: скопировать `tools/run_template.py` → `C:\rvt_stage\gen\run_<имя>.py`,
   подставить плейсхолдеры. Запуск через канал (см. «Канал» ниже). Inline-код в канал
   НЕ слать — только `execfile` файлом.
8. **Гейт**: отчёт `C:\rvt_stage\gen\out\<report_name>.json` (ждать `.done`-семафор,
   свежесть по mtime!). «Готово» = 0 не-PASS строк. Пустой/старый отчёт = FAIL.
   Показ владельцу: `show=True` открывает результат в UI.
9. **Refine** = правка JSON и ПОЛНАЯ пересборка через gen_run (не патчи семейства
   руками). JSON — единственный источник истины.

## Канал (живой стенд)

- MCP `Revit-Connector` подключён → `execute_revit_code` с кодом
  `execfile(r'C:/rvt_stage/gen/run_<имя>.py')`.
- Иначе Routes HTTP напрямую:
  `POST http://localhost:48884/revit_mcp/execute_code/` c телом
  `{"code": "execfile(r'C:/rvt_stage/gen/run_<имя>.py')"}`.
- Revit должен быть запущен с pyRevit (Routes). Проверка: `get_revit_status` или GET на порт.

## Операционные ловушки (краткий слой; полные — в gen_schema.md)

- Кириллица в канал — только данными/execfile UTF-8; пути стейджа ASCII.
- Отчёты: mtime + `.done`; sys.modules-pop в раннере обязателен (кэш IronPython).
- rfa, открытый в UI показом, не перезаписать — save_as уйдёт на `.0002` (норма).
- Каркасный флекс идёт от CurrentType; гейт ставит номинальный тип `gate.type_name`
  (дефолт 'Base') — тип с таким именем должен существовать в каталоге.
- Числа гейта коэрсятся в float автоматически (int валит vf_flex на IronPython).
- Имя Family после загрузки вложения = имя ФАЙЛА rfa, не `family.name` из JSON.
- Линия labeled dim — вдоль оси измерения (x-RP → горизонтальная), иначе №60.
- Модальный диалог Revit блокирует канал (таймаут 60с) — перед прогоном закрыть диалоги.
- sweep/blend в gen_skin — заглушки (отдельная волна); revolve/extrusion/void — боевые;
  extrusion — только plane="level" (вдоль X/Y — боевой путь revolve, паттерн TUBE).
- Нереализованные поля схемы валидатор бьёт FAIL'ом `executor-limit` (список —
  gen_schema.md §Ограничения executor'а) — не обходить, а убирать поле/ждать волну 2.
- gen_run сам гоняет линтер до сборки (строка `validate` в отчёте), но офлайн-прогон
  шага 5 обязателен: полный jsonschema-слой работает только в CPython.
- Величины каталога кроме длин (расход/мощность/ток/масса) — number-колонка + формула
  «* 1 <ед>» (паттерн TUBE): сырой сеттер каталога не конвертирует единицы (airflow
  внутри Revit — фут³/с). Ампер — строго кириллическая «А».

## Tools / Examples

| Файл | Назначение |
|---|---|
| `tools/checklist_suti_semeystva.md` | заполняемый чек-лист «сути семейства» (замечание BIM-менеджера №3) |
| `tools/run_template.py` | шаблон раннера execfile (плейсхолдеры `{{JSON_PATH}}`, `{{REPORT_NAME}}`, `{{OUT_RFA}}`, `{{SHOW}}`) |
| примеры JSON v2 | НЕ копируются в скилл — дом: `Codex/famfab/gen/smoke/` (см. таблицу выше) |

## Разграничение

- Этот скилл = наша связка (метрическая, RU, живой стенд, автогейт, Refine поверх JSON).
- Оригинал `revit-family-generator` (MIT, ArchSmarter) — не трогать; брать только если
  явно нужен JSON схемы v0.1 под C#-аддон FamFab (imperial, без гейта).
- Приёмка стороннего Revit-инструмента → скилл `revit-testbed`; кнопки pyRevit →
  агент `pyrevit-engineer`.
