# Установка, данные и сеть

## Управляемая поверхность

- `~/.codex/AGENTS.md`
- `~/.codex/config.toml` — слияние обязательных ключей без удаления локальных секций
- `~/.codex/hooks.json`
- 16 файлов в `~/.codex/agents/`; соседние локальные агенты сохраняются
- 39 capability-skills + `$sync-base` в `~/.agents/skills/`; соседние локальные skills сохраняются
- `~/.codex/base/cold/`
- `~/.codex/base/runtime/`
- `~/.codex/base/foundation/`
- `~/.codex/base/VERSION` и `components.lock.json`

Foundation заменяет только перечисленные package-owned agents/skills. Неизвестные
локальные соседи не удаляются и не попадают в `quarantined_unknown`; rollback
возвращает прежние версии package-owned файлов и исходный `config.toml`.

## Что не изменяется

`auth.json`, sessions, archived sessions, memories, state/SQLite,
browser/computer-use state, external imports, проекты и рабочие папки.
Foundation хранит собственные transaction state и backups отдельно в
`~/.llm-foundation/`. Install/rollback используют exclusive lock; rollback
перед первой мутацией проверяет hash-bound snapshot и каждый backup-объект,
восстанавливает из staging и завершает recovery-journal только последним
шагом.

## Сеть

- SessionStart: только анонимный `GET` к `api.github.com`, TTL 24 часа,
  без вывода при отсутствии обновления.
- `$sync-base`, обновление: только `gh release list`, `verify`, `download`,
  `verify-asset`.
- Диагностика контекста: локальное чтение выбранных полей TOML; адресный
  `features list` запускается только с явно указанным CLI в пустом home.
  Включение/отключение выполняется по запросу пользователя с резервной копией
  и проверкой остальных значений. Модельные запросы не выполняются; инструкция
  находится в `control-skills/sync-base/references/client-context.md` исходника.
- Foundation engine: полностью offline, сетевого кода нет.
- Consumer upload, push, feedback, telemetry и session-report отсутствуют.

Перед install updater проверяет immutable release и attestation каждого asset,
затем SHA ZIP/manifest/lock/evidence, все release-gates и совпадение внешнего
component lock с embedded-копией. Запускается только Foundation engine,
извлечённый из уже проверенного ZIP и совпавший с его pinned version/hash.
Если post-install `doctor` не проходит, wrapper сразу вызывает rollback.

## Команды

```powershell
# Нативный control-skill внутри Codex
$sync-base

# Найти Foundation, pinned установленным пакетом
$Foundation = Get-ChildItem `
  "$env:USERPROFILE\.codex\base\foundation" `
  -Filter foundation.ps1 -File -Recurse |
  Select-Object -First 1 -ExpandProperty FullName

# Прямая диагностика
$ClientVersion = ((& codex --version) -replace '^codex-cli ', '').Trim()
pwsh -NoProfile -File $Foundation `
  doctor -Home $env:USERPROFILE -Target codex `
  -ClientId codex-cli -ClientVersion $ClientVersion -Json

# Инвентарь
pwsh -NoProfile -File $Foundation `
  inventory -Home $env:USERPROFILE -Target codex -Json

# Откат последней установки
pwsh -NoProfile -File $Foundation `
  rollback -Home $env:USERPROFILE -Target codex -Json
```

## Статическая token-оценка

| Метрика | Legacy hub | Candidate |
| --- | ---: | ---: |
| Base-controlled bytes | 72,077 | 27,616 |
| Оценка tokens `ceil(bytes/3)` | 24,026 | 9,206 |
| Сокращение | — | 61.69% |

Это оценка статического startup/discovery-контекста, а не биллинг провайдера.
Этот отчёт не запускает matched A/B и не доказывает снижение total input
по реальным запросам. Предыдущие результаты применимы только при совпадении
проверяемых байтов и условий. Статический отчёт не является разрешением
на новый модельный прогон. Качество работы проверяется отдельно по
`evals/core/README.md`; экономия контекста его не подтверждает.
