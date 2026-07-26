# project-memory for Codex

This is the native Codex project-memory layout. It deliberately uses the
supported `AGENTS.md` discovery surface and does not install hidden imports,
global project hooks, telemetry, or reverse sync.

```text
<project>/
├── AGENTS.md
└── Codex/
    ├── AGENTS.md
    ├── README.md
    ├── STATUS.md
    ├── КОНТЕКСТ.md
    └── ЖУРНАЛ СЕССИЙ.md
```

Bootstrap:

```powershell
python "$HOME\.agents\skills\project-memory\tools\bootstrap.py" `
  "Project name" --target "<project-root>"
```

The command is idempotent. Existing files are preserved unless an exact
relative path is supplied through `--force`.

Curation is a two-stage, review-required workflow:

```powershell
python "$HOME\.agents\skills\project-memory\tools\curate_rot.py" `
  propose --project "<project-root>"
python "$HOME\.agents\skills\project-memory\tools\curate_rot.py" `
  apply <stamp> --accept p1 --project "<project-root>"
```

No lifecycle hook is enabled by this skill. The only global SessionStart hook
in the Codex base is the silent once-per-day release check.
