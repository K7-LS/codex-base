from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_base.token_audit import audit_static_context  # noqa: E402
from codex_base.release import SUPPORTED_CODEX_CLIENT  # noqa: E402


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
    agent_count = len(agents)
    capability_skill_count = len(skills)
    token = audit_static_context(ROOT)
    token_report = ROOT / "reports" / "static-token-audit.json"
    token_report.parent.mkdir(exist_ok=True)
    token_report.write_text(
        json.dumps(token, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
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
    capabilities = f"""# Возможности Codex-base

## Что Codex знает на старте

Обязательное профессиональное ядро находится непосредственно в `AGENTS.md`:
понимание задачи, совместные решения, обоснованное возражение, проверка
источников, повседневная строительная работа, язык и приёмка результата.
Обычная ВОР относится к основной базе; отдельный модуль выбирают по сложности
процесса. Ядро также задаёт маршруты специалистов и разрешения. WARM discovery
показывает названия, короткие описания и пути {agent_count} агентов, {capability_skill_count} capability-skills
и одного control-skill `$sync-base`.

Полные методологии, скрипты, шаблоны и references на старте неизвестны и не
передаются в контекст. Они читаются только после совпадения задачи с metadata.
Простой разговор выполняется без инструментов, custom agents и reviewers.
Модель и reasoning-level приходят от пользователя/host и базой не задаются.
Доставку ядра проверяют по точному совпадению байтов в установочном payload.
Его предел и запас для проектных инструкций заданы в `context-budget.json`;
совместимость с `project_doc_max_bytes` проверяется тестом. Реальная загрузка
зависит также от клиентских overrides и цепочки проектных инструкций.

## {agent_count} агентов

{_table(agent_rows)}

## {capability_skill_count} capability-skills

{_table(skill_rows)}

Отдельно установлен control-skill `$sync-base`; `/sync-base` распознаётся как
текстовый alias, а не legacy custom prompt.

## COLD-каталог

{chr(10).join(cold_rows)}
"""
    (docs / "CODEX-CAPABILITIES.md").write_text(
        capabilities, encoding="utf-8", newline="\n"
    )

    legacy = token["legacy"]
    candidate = token["candidate"]
    reduction = token["results"]["base_controlled_startup_reduction"] * 100
    operations = f"""# Установка, данные и сеть

## Управляемая поверхность

- `~/.codex/AGENTS.md`
- `~/.codex/config.toml` — слияние обязательных ключей без удаления локальных секций
- `~/.codex/hooks.json`
- {agent_count} файлов в `~/.codex/agents/`; соседние локальные агенты сохраняются
- {capability_skill_count} capability-skills + `$sync-base` в `~/.agents/skills/`; соседние локальные skills сохраняются
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
- `$sync-base`: только `gh release list`, `verify`, `download`,
  `verify-asset`.
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
  "$env:USERPROFILE\\.codex\\base\\foundation" `
  -Filter foundation.ps1 -File -Recurse |
  Select-Object -First 1 -ExpandProperty FullName

# Прямая диагностика
pwsh -NoProfile -File $Foundation `
  doctor -Home $env:USERPROFILE -Target codex `
  -ClientId codex-cli -ClientVersion {SUPPORTED_CODEX_CLIENT} -Json

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
| Base-controlled bytes | {legacy['total_bytes']:,} | {candidate['total_bytes']:,} |
| Оценка tokens `ceil(bytes/3)` | {legacy['estimated_tokens']:,} | {candidate['estimated_tokens']:,} |
| Сокращение | — | {reduction:.2f}% |

Это оценка статического startup/discovery-контекста, а не биллинг провайдера.
Этот отчёт не запускает matched A/B и не доказывает снижение total input
по реальным запросам. Предыдущие результаты применимы только при совпадении
проверяемых байтов и условий. Статический отчёт не является разрешением
на новый модельный прогон. Качество работы проверяется отдельно по
`evals/core/README.md`; экономия контекста его не подтверждает.
"""
    (docs / "INSTALL-AND-NETWORK.md").write_text(
        operations, encoding="utf-8", newline="\n"
    )

    # Dated release checkpoints require fresh evidence, not regeneration.
    # Preserve docs/RELEASE-STATUS.md verbatim.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
