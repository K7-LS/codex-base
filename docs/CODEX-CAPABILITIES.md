# Возможности Codex-base

## Что Codex знает на старте

На каждом новом сеансе загружается только HOT-слой: компактные запреты,
маршрутизация основных строительных доменов, reviewer/risk gates,
token-дисциплина, lazy dependency policy и one-way sync. WARM discovery
показывает названия, короткие описания и пути 16 агентов, 38 capability-skills
и одного control-skill `$sync-base`.

Полные методологии, скрипты, шаблоны и references на старте неизвестны и не
передаются в контекст. Они читаются только после совпадения задачи с metadata.
Простой разговор выполняется без инструментов, custom agents и reviewers.
Модель и reasoning-level приходят от пользователя/host и базой не задаются.

## 16 агентов

| Agent | Назначение | Доступ | Зависимости |
| --- | --- | --- | --- |
| `audit-rd-section` | Проверяет один раздел ПД/РД на соответствие ГОСТ, СПДС и профильным нормам. | RO | `core.files.read` |
| `auditor` | Независимо сверяет итоговый артефакт с ТЗ и источниками, включая количества, модели и ссылки. | RO | `core.files.read` |
| `designer` | Проектирует ОВ, ВК, ЭО и СС, выполняет инженерные расчёты и подбор оборудования. | RW | `core.files.read`, `core.files.write` |
| `excel-validator` | Read-only проверка XLSX: формулы, типы, дубли, диапазоны и целостность таблицы. | RO | `spreadsheet.read` |
| `expertiza-responder` | Готовит структурированные ответы на замечания государственной или негосударственной экспертизы. | RW | `core.files.read`, `document.word.write` |
| `id-engineer` | Оформляет исполнительную документацию, акты, журналы и реестры по факту выполненных работ. | RW | `core.files.read`, `document.word.write` |
| `kp-writer` | Собирает исходящее коммерческое предложение заказчику из ТЗ, объёмов, цен и условий. | RW | `core.files.read`, `document.word.write` |
| `letter-writer` | Готовит исходящие деловые письма, запросы, уведомления, претензии и сопроводительные. | RW | `core.files.read`, `document.word.write` |
| `norm-lookup` | Находит точный пункт, редакцию и дословную короткую цитату нормативного документа. | RO | `core.files.read`, `web.search` |
| `pdf-reviewer` | Read-only проверка PDF как файла: структура, страницы, формы, ссылки, шрифты и аннотации. | RO | `pdf.read`, `pdf.render` |
| `pto-engineer` | Считает объёмы по готовым чертежам и формирует ВОР, спецификации и пояснительные записки. | RW | `core.files.read`, `spreadsheet.write` |
| `pyrevit-engineer` | Пишет и проверяет pyRevit-инструменты на IronPython и Revit API с обязательным live-gate. | RW | `core.files.read`, `core.files.write`, `revit.inspect` |
| `rd-coordinator` | Read-only сверяет согласованность данных между разделами АР, КР, ОВ, ВК, ЭО и СС. | RO | `core.files.read` |
| `smetchik` | Составляет локальные сметы, подбирает расценки, индексы, НР, СП, НДС, КС-2 и КС-3. | RW | `core.files.read`, `spreadsheet.write` |
| `snabzhenets` | Разбирает УПД и входящие КП, сравнивает поставщиков и формирует закупочные заявки. | RW | `core.files.read`, `spreadsheet.write` |
| `word-checker` | Read-only проверка DOCX: структура, стили, таблицы, изображения и незаполненные шаблоны. | RO | `document.word.read` |

## 38 capability-skills

| Skill | Когда загружается | Зависимости |
| --- | --- | --- |
| `$acad-recreation` | Use when нужно воссоздать инженерный DWG по PDF, скану или образцу. | `cad.read`, `cad.write` |
| `$cad-reader` | Use when нужно прочитать геометрию, слои или блоки DWG/DXF. | `cad.read` |
| `$chains-pattern` | Use when задаче нужна именованная цепочка навыков и проверок. | `core.files.read` |
| `$co-verify` | Use when нужно точно сверить две спецификации оборудования. | `core.files.read` |
| `$doc-extract` | Use when нужно извлечь текст или таблицы из PDF и сканов. | `pdf.read`, `pdf.render` |
| `$doc-finder` | Use when нужен сертификат, паспорт или декларация на изделие. | `web.search`, `web.fetch` |
| `$domain-grilling` | Use when инженерной задаче не хватает критичных вводных. | `core.files.read` |
| `$excel-helper` | Use when нужно прочитать, изменить или проверить XLSX. | `spreadsheet.read`, `spreadsheet.write` |
| `$facts-layer` | Use when проекту нужен проверяемый единый слой фактов. | `core.files.read`, `core.files.write` |
| `$graphify` | Use when нужно понять структуру и связи большой базы. | `core.files.read`, `core.shell.execute` |
| `$handoff-to-new-chat` | Use when работу нужно передать в новую чистую задачу Codex. | `core.files.read`, `core.files.write` |
| `$id-tom-priemka` | Use when PDF-том ИД нужно постранично принять перед сдачей. | `pdf.read`, `pdf.render` |
| `$image-text-replace` | Use when в скане или изображении нужно заменить текст. | `image.read`, `image.write` |
| `$karpathy-guidelines` | Use when существенная реализация рискует стать избыточной. | `core.files.read` |
| `$llm-interop` | Use when задача передаётся между Codex, Claude и OpenCode. | `core.files.read`, `core.shell.execute` |
| `$local-osint-recon` | Use when authorized local OSINT or recon must run through an existing Kali WSL. | `core.shell.execute` |
| `$local-video-digest` | Use when локальному видео нужен контактный лист и конспект. | `video.read` |
| `$pd-tep-extractor` | Use when из ПД нужно извлечь ТЭП со ссылками на источник. | `pdf.read` |
| `$pdf-edit` | Use when нужно изменить страницы, формы или аннотации PDF. | `pdf.read`, `pdf.write` |
| `$pnr-vor-helper` | Use when нужно собрать комплект ПНР и ВОР. | `document.word.write`, `spreadsheet.write` |
| `$project-memory` | Use when проекту нужна локальная память решений и статуса. | `core.files.read`, `core.files.write` |
| `$revit-family-generator` | Use when нужно сгенерировать определение семейства Revit. | `revit.execute` |
| `$revit-family-generator-ru` | Use when семейство Revit нужно собрать в RU/мм-профиле. | `revit.execute` |
| `$revit-testbed` | Use when Revit-инструмент нужно принять на живом стенде. | `revit.inspect`, `revit.execute` |
| `$ru-gov-access` | Use when нужен российский госреестр с гео-ограничениями. | `web.fetch`, `web.browser.interact` |
| `$ru-writing-style` | Use when пишешь или правишь русский текст для человека — письмо, КП, пояснительную записку, ответ экспертизе, отчёт, ТЗ, статью. |  |
| `$skill-development` | Use when создаётся или изменяется повторно используемый навык. | `core.files.read`, `core.files.write` |
| `$spec-writer` | Use when нужна спецификация оборудования в XLSX или DOCX. | `spreadsheet.write`, `document.word.write` |
| `$stroy-formatting` | Use when строительный документ нужно оформить по образцу. | `document.word.write` |
| `$structured-artifacts` | Use when контекст нужно вынести в файлы состояния и решений. | `core.files.read`, `core.files.write` |
| `$supervisor` | Use when явно нужен надзор за автономным Codex. | `core.files.read` |
| `$supplier-due-diligence` | Use when нужно проверить поставщика или подлинность документа. | `web.search`, `web.fetch` |
| `$svor-vor-works-base` | Use when строки СВОР/ВОР нужно унифицировать или сопоставить. | `core.files.read`, `spreadsheet.write` |
| `$understanding-map` | Use when полезна карта понимания задачи, входов и рисков. | `core.files.read` |
| `$upd-parser` | Use when УПД или накладную нужно разобрать в структуру. | `pdf.read`, `spreadsheet.write` |
| `$web-access` | Use when нужно открыть страницу, скачать или проверить источник. | `web.fetch` |
| `$word-helper` | Use when нужно прочитать, изменить или проверить DOCX. | `document.word.read`, `document.word.write` |
| `$yandex-disk-uploader` | Use when готовый файл нужно загрузить на Яндекс Диск. | `yandex.upload` |

Отдельно установлен control-skill `$sync-base`; `/sync-base` распознаётся как
текстовый alias, а не legacy custom prompt.

## COLD-каталог

- `memory/sessions_policy.md`
- `memory/harvest_workflow.md`
- `memory/harvest_proactive.md`
- `memory/auto_sync.md`
- `memory/role_detection.md`
- `memory/proxy_github.md`
- `memory/reference_mcp.md`
- `memory/reference_agents.md`
- `memory/auto_memory_policy.md`
- `memory/context_discipline.md`
- `memory/profanity_marker.md`
- `memory/feedback_web_direct_access.md`
- `memory/feedback_webfetch_reality_check.md`
- `memory/named_chains.md`
- `memory/reference_pyrevit.md`
- `memory/reference_revit_mcp.md`
- `memory/reference_docx_editing_failures.md`
- `memory/reference_hybrid_ai_pipeline.md`
- `memory/reference_inkscape_pdf_editing.md`
- `memory/reference_officecli.md`
- `chains/docx-from-template.md`
- `chains/pdf-scan-extract.md`
- `chains/upd-to-spec-reconcile.md`
- `commands/format.md`
- `commands/harvest.md`
- `commands/sync-base.md`
