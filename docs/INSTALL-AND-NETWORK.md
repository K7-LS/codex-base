# Установка, данные и сеть

## Управляемая поверхность

- `~/.codex/AGENTS.md`
- `~/.codex/config.toml`
- `~/.codex/hooks.json`
- `~/.codex/agents/` — exact directory, 16 TOML-агентов
- `~/.agents/skills/` — exact directory, 37 capability-skills + `$sync-base`
- `~/.codex/base/cold/`
- `~/.codex/base/runtime/`
- `~/.codex/base/foundation/`
- `~/.codex/base/VERSION` и `components.lock.json`

Неизвестные старые agents/skills включаются в полный snapshot, перечисляются
как `quarantined_unknown`, удаляются из active discovery и возвращаются
rollback'ом.

## Что не изменяется

`auth.json`, sessions, archived sessions, memories, state/SQLite,
browser/computer-use state, external imports, проекты и рабочие папки.
Foundation хранит собственные transaction state и backups отдельно в
`~/.llm-foundation/`.

## Сеть

- SessionStart: только анонимный `GET` к `api.github.com`, TTL 24 часа,
  без вывода при отсутствии обновления.
- `$sync-base`: только `gh release list`, `verify`, `download`,
  `verify-asset`.
- Foundation engine: полностью offline, сетевого кода нет.
- Consumer upload, push, feedback, telemetry и session-report отсутствуют.

## Команды

```powershell
# Нативный control-skill внутри Codex
$sync-base

# Прямая диагностика
pwsh -NoProfile -File "$env:USERPROFILE\.codex\base\foundation\0.1.0\foundation.ps1" `
  doctor -Home $env:USERPROFILE -Target codex `
  -ClientId codex-cli -ClientVersion 0.146.0-alpha.3.1 -Json

# Инвентарь
pwsh -NoProfile -File "$env:USERPROFILE\.codex\base\foundation\0.1.0\foundation.ps1" `
  inventory -Home $env:USERPROFILE -Target codex -Json

# Откат последней установки
pwsh -NoProfile -File "$env:USERPROFILE\.codex\base\foundation\0.1.0\foundation.ps1" `
  rollback -Home $env:USERPROFILE -Target codex -Json
```

## Статическая token-оценка

| Метрика | Legacy hub | Candidate |
| --- | ---: | ---: |
| Base-controlled bytes | 72,077 | 13,133 |
| Оценка tokens `ceil(bytes/3)` | 24,026 | 4,378 |
| Сокращение | — | 81.78% |

Это оценка статического startup/discovery-контекста, а не биллинг провайдера.
Matched A/B пока не запускался, поэтому снижение total input по реальным
запросам ещё не доказано.
