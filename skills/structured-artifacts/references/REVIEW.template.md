---
artifact: REVIEW
project: <название>
phase: <имя фазы>
reviewer: <agent name — auditor / word-checker / excel-validator / pdf-reviewer>
reviewed_at: <YYYY-MM-DD>
verdict: PASSED | NOT_PASSED | NEEDS_REVISION
---

# REVIEW — <имя фазы>

## TL;DR

<3-5 строк: что проверено, какой verdict, ключевые findings>.

## Verdict

**PASSED / NOT_PASSED / NEEDS_REVISION**

<Одна фраза-обоснование>.

## Что проверено

- `<файл/артефакт 1>` — <что именно проверял>
- `<файл/артефакт 2>` — <что именно проверял>
- `<область методики 3>` — <что проверял>

## Findings

### BLOCKER (mandatory fix)

- **`<файл>:<строка>` — <короткое название findinga>**
  - Что: <описание проблемы>
  - Почему BLOCKER: <обоснование критичности>
  - Как исправить: <конкретное предложение>

### MAJOR (should fix)

- **`<файл>:<строка>` — <название>**
  - <описание + предложение>

### MINOR (nice to have)

- **`<файл>:<строка>` — <название>**
  - <описание + предложение>

## Что НЕ проверял

<Явный список ограничений: что было вне scope этого ревью.
Помогает следующему ревьюеру понять что осталось.>

## Next steps

- <Action 1 — кому>
- <Action 2 — кому>

## Связанное

- `PLAN.md` — план фазы (что должно было быть сделано).
- `STATE.md` — обновить после применения BLOCKER/MAJOR findings.
- `DECISIONS.md` — если ревьюер выявил design issue, требующее
  пересмотра решения — записать туда.
