---
name: project-memory
description: Native Codex project memory with explicit bootstrap and reviewed curation.
---

# project-memory

Use this skill when a project needs durable, inspectable context across Codex
tasks without adding its full history to every startup prompt.

## Bootstrap

Run:

```powershell
python "$HOME\.agents\skills\project-memory\tools\bootstrap.py" `
  "Project name" --target "<project-root>" --role "<role>" --domain "<domain>"
```

The command creates, without overwriting existing files:

- `<project-root>/AGENTS.md` — compact entrypoint discovered natively by Codex;
- `<project-root>/Codex/AGENTS.md` — project rules;
- `<project-root>/Codex/STATUS.md` — current state and next step;
- `<project-root>/Codex/КОНТЕКСТ.md` — role, acceptance criteria and pitfalls;
- `<project-root>/Codex/ЖУРНАЛ СЕССИЙ.md` — compact task journal;
- `<project-root>/Codex/README.md` — navigation.

Use `--force <relative-path>` only after showing the exact target to the user.
The bare name `AGENTS.md` is intentionally ambiguous; use `./AGENTS.md` or
`Codex/AGENTS.md`.

Codex reads the root `AGENTS.md` through its native project discovery. Follow
its instruction to read the compact status and journal. Do not install a
project hook globally.

## Reviewed curation

Run the read-only proposal stage:

```powershell
python "$HOME\.agents\skills\project-memory\tools\curate_rot.py" `
  propose --project "<project-root>"
```

Read `Codex/.curate/<stamp>/REPORT.md`, inspect each proposal, and ask for an
explicit decision. Apply only accepted IDs:

```powershell
python "$HOME\.agents\skills\project-memory\tools\curate_rot.py" `
  apply <stamp> --accept p1,c2 --project "<project-root>"
```

The apply stage creates `Codex/_backup_<date>/` first. Never auto-apply, invent
missing facts, or write outside the project memory surface.

## Boundaries

- All stored paths are relative to the project root.
- Personal instructions belong in the project `AGENTS.md`, not a hidden global
  user layer.
- The skill performs no network calls, feedback upload, telemetry, or automatic
  session-report transmission.
- Keep each journal entry compact: date, device, result, touched files, next
  step.
- Use `facts-layer` for factual values and link to it from `STATUS.md`.
