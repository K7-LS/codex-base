# project-memory for K7 LLM clients

This is the shared project-memory layout. It emits native root entrypoints and
does not install hidden imports,
global project hooks, telemetry, or reverse sync.

```text
<project>/
├── AGENTS.md
├── CLAUDE.md
└── LLM/
    ├── AGENTS.md
    ├── README.md
    ├── STATUS.md
    ├── КОНТЕКСТ.md
    └── ЖУРНАЛ СЕССИЙ.md
```

Bootstrap:

```powershell
python <skill-root>/tools/bootstrap.py `
  "Project name" --target "<project-root>"
```

The command is idempotent. Existing files are preserved unless an exact
relative path is supplied through `--force`.

Curation is a two-stage, review-required native custom agent plan:

```powershell
python <skill-root>/tools/curate_rot.py `
  propose --project "<project-root>"
python <skill-root>/tools/curate_rot.py `
  apply <stamp> --accept p1 --project "<project-root>"
```

No lifecycle hook is enabled by this skill.
