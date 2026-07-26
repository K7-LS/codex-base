from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def _table(rows: list[list[str]]) -> str:
    header = rows[0]
    body = rows[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def main() -> int:
    agents = _read("catalog/agents.json")
    skills = _read("catalog/skills.json")
    cold = _read("catalog/cold.json")
    token = _read("reports/static-token-audit.json")
    summary = _read("reports/offline-acceptance-summary.json")
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)

    agent_rows = [["Agent", "Назначение", "Доступ", "Зависимости"]]
    for item in agents:
        agent_rows.append(
            [
                f"`{item['id']}`",
                item["description"],
                item["permission_class"].upper(),
                ", ".join(f"`{value}`" for value in item["required_capabilities"]),
            ]
        )
    skill_rows = [["Skill", "Когда загружается", "Зависимости"]]
    for item in skills:
        skill_rows.append(
            [
                f"`${item['id']}`",
                item["description"],
                ", ".join(f"`{value}`" for value in item["required_capabilities"]),
            ]
        )
    cold_rows = [
        f"- `{value}`"
        for group in ("memory", "chains", "commands")
        for value in cold[group]
    ]
    capabilities = f"""# Возможности Codex-base 0.1.0

## Что Codex знает на старте

На каждом новом сеансе загружается только HOT-слой: компактные запреты,
маршрутизация основных строительных доменов, reviewer/risk gates,
token-дисциплина, lazy dependency policy и one-way sync. WARM discovery
показывает названия, короткие описания и пути 16 агентов, 37 capability-skills
и одного control-skill `$sync-base`.

Полные методологии, скрипты, шаблоны и references на старте неизвестны и не
передаются в контекст. Они читаются только после совпадения задачи с metadata.
Простой разговор выполняется без инструментов, custom agents и reviewers.
Модель и reasoning-level приходят от пользователя/host и базой не задаются.

## 16 агентов

{_table(agent_rows)}

## 37 capability-skills

{_table(skill_rows)}

Отдельно установлен control-skill `$sync-base`; `/sync-base` распознаётся как
текстовый alias, а не legacy custom prompt.

## COLD-каталог

{chr(10).join(cold_rows)}
"""
    (docs / "CODEX-CAPABILITIES.md").write_text(
        capabilities, encoding="utf-8"
    )

    legacy = token["legacy"]
    candidate = token["candidate"]
    reduction = token["results"]["base_controlled_startup_reduction"] * 100
    operations = f"""# Установка, данные и сеть

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
pwsh -NoProfile -File "$env:USERPROFILE\\.codex\\base\\foundation\\0.1.0\\foundation.ps1" `
  doctor -Home $env:USERPROFILE -Target codex `
  -ClientId codex-cli -ClientVersion 0.146.0-alpha.3.1 -Json

# Инвентарь
pwsh -NoProfile -File "$env:USERPROFILE\\.codex\\base\\foundation\\0.1.0\\foundation.ps1" `
  inventory -Home $env:USERPROFILE -Target codex -Json

# Откат последней установки
pwsh -NoProfile -File "$env:USERPROFILE\\.codex\\base\\foundation\\0.1.0\\foundation.ps1" `
  rollback -Home $env:USERPROFILE -Target codex -Json
```

## Статическая token-оценка

| Метрика | Legacy hub | Candidate |
| --- | ---: | ---: |
| Base-controlled bytes | {legacy['total_bytes']:,} | {candidate['total_bytes']:,} |
| Оценка tokens `ceil(bytes/3)` | {legacy['estimated_tokens']:,} | {candidate['estimated_tokens']:,} |
| Сокращение | — | {reduction:.2f}% |

Это оценка статического startup/discovery-контекста, а не биллинг провайдера.
Matched A/B пока не запускался, поэтому снижение total input по реальным
запросам ещё не доказано.
"""
    (docs / "INSTALL-AND-NETWORK.md").write_text(
        operations, encoding="utf-8"
    )

    status = f"""# Release status

Candidate ZIP SHA-256: `{summary['candidate_zip_sha256']}`.

| Gate | Verdict |
| --- | --- |
| `FOUNDATION_SYNTHETIC` | `{summary['FOUNDATION_SYNTHETIC']}` |
| `CANDIDATE_OFFLINE` | `{summary['CANDIDATE_OFFLINE']}` |
| `MATCHED_AB` | `{summary['MATCHED_AB']}` |
| `CODEX_CANARY` | `{summary['CODEX_CANARY']}` |
| `FULL_RELEASE_CODEX` | `{summary['FULL_RELEASE_CODEX']}` |
| `PROGRAM_RELEASE` | `{summary['PROGRAM_RELEASE']}` |

`CANDIDATE_OFFLINE: PASS` подтверждает deterministic package, 38/38
Codex-contract tests, fresh Foundation evidence (23/23), а также реальный
fake-home lifecycle в PowerShell 7 и Windows PowerShell 5.1.

Не проверено и не разрешено:

- paid matched A/B на Terra/Sol;
- изменение текущего `~/.codex`;
- hub canary;
- stable GitHub Release и immutable/asset attestation на опубликованном tag;
- employee rollout;
- нативные реализации `claude-base-v2` и `opencode-base`.

Поэтому `FULL_RELEASE_CODEX` остаётся `NOT_PASS`, а общий program verdict —
`0/3`.
"""
    (docs / "RELEASE-STATUS.md").write_text(status, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
