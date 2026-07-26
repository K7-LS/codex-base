# Дисциплина контекстного окна и proactive handoff (вынесено из AGENTS.md)

Загружать по триггерам: «давай в новый чат», «контекст полный», «handoff»,
«передай в новую сессию», ИЛИ когда сам замечаешь признаки перегруза.
Полные thresholds — скилл `handoff-to-new-chat`. Вынос контекста на диск — скилл
`structured-artifacts`.

Длинные сессии (70+ tool calls, 30+ user turns) перегружают context window — Codex
начинает «забывать» ранние решения и терять точность.

## Proactive-триггеры (Codex сам предлагает handoff)

Двухуровневая система **WARNING / CRITICAL** (заим из GSD Redux, см. `harvested/gsd-redux.md`).

**WARNING (~60% утилизация)** — 1-2 признака → не handoff, но дисциплинировать
(cascade loading, offset/limit, Agent для исследований).

**CRITICAL (~70% утилизация)** — **два и более** одновременно → Codex сам вызывает
`request_user_input` с предложением handoff:
- 5+ Read больших файлов (> 200 строк) в сессии
- 3+ Agent (subagent) вызовов с большими ответами
- 30+ user turns
- 5+ объёмных Bash outputs (> 200 строк stdout)
- 5+ Edit/Write на разные файлы
- 3+ параллельные branches задач

> Примечание: эвристики 60%/70% некалиброваны для окна 1M (MAX). Там ориентир —
> UI-индикатор, а не эти оценки. См. `projects/.../memory/feedback_context_heuristics_1m.md`.

## Дисциплина контекста (профилактика)
1. **Cascade loading** — читать только нужную секцию большого файла. Сначала `core.search.text`
   на заголовки, потом `Read offset=N limit=50`. Не читать всё целиком.
2. **Structured artifacts** для проектов в 3+ фазы — выносить контекст в
   `ROADMAP.md`/`STATE.md`/`PLAN.md`/`REVIEW.md`/`DECISIONS.md` на диск.
3. **Tool outputs через фильтры** — `| tail -5`, `| grep PATTERN`. Не walls of text.
4. **Длинные исследования через Agent** — для 5+ файлов делегировать в
   `Agent(subagent_type="Explore"/"general-purpose")`. Возвращает summary.
5. **Background для долгих команд** — `run_in_background=true` для процессов > 30 сек.
6. **Не дублировать рассуждения** — ссылаться на план выше, не пересказывать.

## Когда handoff vs `/compact`
- **handoff-to-new-chat** — задача важная, нужна точность, есть open questions.
  Новый чат с briefing'ом + полный session-report.
- **`/compact`** — задача простая, достаточно сжатого контекста в той же сессии.
  Менее надёжно для критичных задач (compaction lossy).
