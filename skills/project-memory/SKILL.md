---
name: project-memory
description: Use when проекту нужна локальная память решений и статуса.
---

# project-memory

Use this skill when a project needs durable, inspectable context across LLM
tasks without adding its full history to every startup prompt.

## Bootstrap

Run:

```powershell
python <skill-root>/tools/bootstrap.py `
  "Project name" --target "<project-root>" --role "<role>" --domain "<domain>"
```

The command creates, without overwriting existing files:

- `<project-root>/AGENTS.md` and `CLAUDE.md` — native compact entrypoints;
- `<project-root>/LLM/AGENTS.md` — shared project rules;
- `<project-root>/LLM/STATUS.md` — current state and next step;
- `<project-root>/LLM/КОНТЕКСТ.md` — role, acceptance criteria and pitfalls;
- `<project-root>/LLM/ЖУРНАЛ СЕССИЙ.md` — compact journal;
- `<project-root>/LLM/README.md` — navigation.

Use `--force <relative-path>` only after showing the exact target to the user.
The native client reads its root entrypoint and is directed to the same `LLM/`
state. Do not install a project hook globally.

## Reviewed curation

Run the read-only proposal stage:

```powershell
python <skill-root>/tools/curate_rot.py `
  propose --project "<project-root>"
```

Read `LLM/.curate/<stamp>/REPORT.md`, inspect each proposal, and ask for an
explicit decision. Apply only accepted IDs:

```powershell
python <skill-root>/tools/curate_rot.py `
  apply <stamp> --accept p1,c2 --project "<project-root>"
```

The apply stage creates `LLM/_backup_<date>/` first. Never auto-apply, invent
missing facts, or write outside the project memory surface.

## Boundaries

- All stored paths are relative to the project root.
- Personal instructions belong in the project's native root instructions, not
  a hidden global user layer.
- The skill performs no network calls, feedback upload, telemetry, or automatic
  session-report transmission.
- Keep each journal entry compact: date, device, result, touched files, next
  step.
- Use `facts-layer` for factual values and link to it from `STATUS.md`.
