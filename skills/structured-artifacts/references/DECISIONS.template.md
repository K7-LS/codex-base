---
artifact: DECISIONS
project: <название>
created: <YYYY-MM-DD>
mode: append-only
---

# DECISIONS — design decisions журнал

> **Append-only.** Не редактировать прошлые записи. При пересмотре —
> добавить новую запись с пометкой `revised: см. ADR-NNN`. Каждая
> запись имеет ID `ADR-NNN` (Architectural Decision Record).

---

## ADR-001 — <короткое название решения>

**Date:** <YYYY-MM-DD>
**Status:** active | superseded by ADR-NNN | abandoned
**Made by:** <main / agent / user>

### Context

<2-3 строки: какая проблема стояла, что пытались решить>.

### Options considered

| # | Вариант | Pro | Contra |
|---|---------|-----|--------|
| 1 | <вариант> | <…> | <…> |
| 2 | <вариант> | <…> | <…> |

### Decision

<Что выбрали и одной фразой почему>.

### Rationale

<3-5 строк: ключевые аргументы. Что было ВАЖНО для решения, что
было НЕВАЖНО (это часто полезнее всего для будущего себя)>.

### Consequences

- Положительные: <…>
- Отрицательные / trade-offs: <…>
- Что станет видно только через несколько фаз: <…>

### Related

- `ROADMAP.md` фаза: <…>
- `PLAN.md` step: <…>
- ADR-XXX (если связано с другим решением)

---

## ADR-002 — <следующее решение>

…
