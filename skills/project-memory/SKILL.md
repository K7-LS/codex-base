---
name: project-memory
description: Use when проекту нужна локальная память решений и статуса.
---

# project-memory

Use this skill when a project needs durable, inspectable context across LLM
tasks without adding its full history to every startup prompt.

## Existing canon first

Read local entrypoints and find the accepted project files for facts, decisions
and status before choosing any storage layout. Reuse that canon regardless of
its name or client; an existing `Claude/` canon does not call for a new `LLM/`.
Check relevant recent decisions and actual artifacts before relying on old status.

Establish the permitted location and basis for writing. Existing authorization
or applicable project rules may cover the update; do not ask again when they do.
If either is unclear, prepare the proposed note and clarify it. Never write to
client memories, sessions or state, or create a parallel project canon.

## Bootstrap

Use the helper only when a new `LLM/` canon is needed and authorized, or when
authorized to fill missing files in an already accepted `LLM/` layout. It does
not detect a different existing canon; checking that is the caller's job.

For that layout, run:

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

Use `--force <relative-path>` only when overwriting that exact target is authorized.
The native client reads its root entrypoint and is directed to the same `LLM/`
state. Do not install a project hook globally.

## Reviewed curation

The helper below supports the `LLM/` layout only. For another accepted canon,
review the existing files directly; do not migrate or create `LLM/` to fit the tool.

The proposal stage leaves source files unchanged but writes review artifacts to
`LLM/.curate/`. Run it only when that output is within the authorized scope:

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
- Store only useful, supported decisions and lessons; distinguish facts,
  assumptions and open choices. Name the responsible writer when delegating
  updates so agents do not overwrite shared status or duplicate decisions.
- Use `facts-layer` for factual values where needed and link the accepted
  registry from the project's existing status file.
