---
name: structured-artifacts
description: Use when контекст нужно вынести в файлы состояния и решений.
---

# structured-artifacts — выносить контекст в md-файлы на диске

## Зачем

Длинные задачи (3+ фаз, многоагентские) переполняют контекст. Каждый
агент тащит «простыню» рассуждений, главный Codex забывает ранние
решения. Решение: контекст крупной задачи живёт **на диске** в 5
структурированных артефактах. Агенты читают только свою часть.

Базовый принцип дисциплины контекста: тяжёлый рабочий контекст не держать
в чате, а выносить на диск и читать cascade-loading'ом только нужную часть.
Подробно — `memory/context_discipline.md`.

## Когда подключать

- Задача распадается на 3+ фазы с зависимостями между ними.
- В flow задействовано 3+ агентов (designer + auditor + writer + ...).
- Контекст-индикатор подходит к WARNING (~60%) и видно что задача
  ещё не близко к концу.
- Запросов вида «помоги собрать комплект <раздел>», «оркестрируй
  работу по проекту», «несколько фаз», «несколько разделов».

## Когда НЕ подключать

- Одношаговая задача — overhead 5 файлов не окупается.
- Только один агент работает — нет смысла «отчуждать» контекст.
- Быстрая задача < 10 user turns — простыня в чате ещё нормально.
- Уже есть подходящий [[chains-pattern|named chain]] под этот flow —
  использовать chain, не выносить руками.

## 5 артефактов (Concept 2 из gsd-redux)

| Файл | Размер | Кто читает | Кто пишет | Назначение |
|---|---|---|---|---|
| `ROADMAP.md` | 1-5 KB | все | main | Общий план фаз. 1 фраза на фазу. |
| `STATE.md` | 1-3 KB | все | main + agents | Текущее состояние: progress, in_progress, blocked. |
| `PLAN.md` | 5-30 KB | агент **текущей** фазы | main | Детальный план фазы. После закрытия — архивируется. |
| `REVIEW.md` | 5-20 KB | main + fixer | auditor | Findings с file/line refs. Per-фаза или общий. |
| `DECISIONS.md` | 5-15 KB | все | main + agents | Append-only. «Почему» для будущего себя. |

Шаблоны — в `references/`:

- [[references/ROADMAP.template.md]] — общий план
- [[references/STATE.template.md]] — состояние
- [[references/PLAN.template.md]] — детальный план фазы
- [[references/REVIEW.template.md]] — findings ревьюера
- [[references/DECISIONS.template.md]] — design decisions

## Где хранятся

**В рабочей папке пользователя**, рядом с финальными артефактами:

```
<project-cwd>/
├── _meta/                  # ← структурированные артефакты ЗДЕСЬ
│   ├── ROADMAP.md
│   ├── STATE.md
│   ├── PLAN.md
│   ├── REVIEW.md
│   └── DECISIONS.md
├── ПЗ.docx                 # ← финальные артефакты для пользователя
├── Спецификация.xlsx
└── ...
```

**НЕ в `~/.codex/base/`** — это рабочий контекст конкретного проекта,
не методическая база. После сдачи проекта `_meta/` можно архивировать
или удалить.

## Cascade loading — правила чтения

**Главный Codex (orchestrator):**
- При старте сессии: `Read _meta/ROADMAP.md` (весь) + `Read _meta/STATE.md` (весь).
- Этого хватает чтобы понять где мы и что делать дальше.

**Доменный агент (designer / pto-engineer / kp-writer ...):**
- В промпте от orchestrator'а: «прочитай `_meta/PLAN.md` секцию `Phase 3`».
- Агент делает `Grep -n "^## Phase 3" _meta/PLAN.md` чтобы найти offset,
  потом `Read _meta/PLAN.md offset=N limit=50`.
- НЕ читать весь PLAN.md если фаз > 2.

**Auditor / валидаторы:**
- Читают `_meta/PLAN.md` для контекста задачи (только текущая фаза).
- Читают артефакты для проверки (docx/xlsx/pdf).
- Пишут `_meta/REVIEW.md` — append «Phase N — verdict: ...» секции.

**Все агенты после своей работы:**
- Обновляют `_meta/STATE.md`: что сделано, что in_progress, что blocked.
- Если приняли важное архитектурное решение — append в `_meta/DECISIONS.md`.

## Lifecycle типичной задачи

```
1. main создаёт _meta/, копирует 5 шаблонов из references/.
2. main заполняет ROADMAP.md (фазы) и STATE.md (Phase 1 in_progress).
3. main пишет PLAN.md для Phase 1.
4. main спавнит доменного агента: «выполни Phase 1, см. _meta/PLAN.md».
5. Доменный агент работает, обновляет STATE.md, пишет в DECISIONS.md если нужно.
6. main спавнит auditor: «ревью Phase 1, найди в _meta/REVIEW.md».
7. main читает REVIEW.md, при PASSED — закрывает Phase 1 в STATE.md,
   архивирует PLAN.md как PLAN_PHASE1.md, пишет новый PLAN.md для Phase 2.
8. Повтор шагов 4-7 для следующих фаз.
9. После последней фазы — main выдаёт пользователю финальный артефакт
   (docx/xlsx/pdf), _meta/ остаётся на диске как «отчёт о работе».
```

## Связь с другими механизмами

- **[[chains-pattern]]** — если flow повторяется в 3+ сессиях,
  формализовать как named chain. Chain **внутри** использует
  structured-artifacts pattern.
- **[[handoff-to-new-chat]]** — если контекст подходит к CRITICAL,
  сначала вынести в `_meta/`, потом handoff. В новой сессии достаточно
  прочитать `ROADMAP.md` + `STATE.md` для briefing'а.
- **[[karpathy-guidelines]] §4 (Цели и верификация)** — `STATE.md`
  явно содержит критерии завершения каждой фазы, не «всё ок».

## Anti-patterns

- **Не создавать `_meta/` для одноразовой задачи** — overhead больше выгоды.
- **Не дублировать ROADMAP.md в чате** — главное правило: ссылаться
  «см. `_meta/ROADMAP.md`», а не пересказывать.
- **Не делать `_meta/` в `~/.codex/base/`** — это рабочий контекст проекта,
  не методическая база.
- **Не читать все 5 файлов целиком на старте** — cascade loading
  (Grep заголовков → Read offset/limit). См. [[karpathy-guidelines]] §3
  (хирургические правки).
- **Не оставлять STATE.md устаревшим** — после каждой существенной
  правки обновлять `last_updated` во frontmatter и progress-таблицу.
- **DECISIONS.md — append-only**. Не редактировать прошлые решения,
  а добавлять новое «2026-MM-DD revised: …».

## Источник методологии

- **Концепт 2** из gsd-redux (gsd-build/get-shit-done, MIT, 63K stars).
- Адоптировано: SKILL.md + 5 шаблонов в `references/`, методика
  cascade loading.
- Изменено vs upstream: имена файлов остались (ROADMAP/STATE/PLAN/REVIEW/
  DECISIONS), но scope — наши документ-driven задачи (не software).
  AI-SPEC.md из gsd-redux **не адоптирован** (не нужен для наших задач).
