from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_base.token_audit import audit_static_context  # noqa: E402


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
        capabilities, encoding="utf-8", newline="\n"
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
  -ClientId codex-cli -ClientVersion 0.146.0-alpha.3.1 -Json

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
Matched A/B пока не запускался, поэтому снижение total input по реальным
запросам ещё не доказано. Владелец разрешил ровно один guarded-прогон:
legacy/candidate × «привет»/«что ты умеешь» на GPT-5.6 Terra, low reasoning.
Повтор или расширение матрицы требует нового разрешения.
"""
    (docs / "INSTALL-AND-NETWORK.md").write_text(
        operations, encoding="utf-8", newline="\n"
    )

    status = """# Release status

Авторитетные hash и offline-вердикты не хранятся как изменяемый tracked-report.
Они формируются `tools/run_acceptance.py` только из чистого Git commit/tree и
попадают в `dist/candidate-X.Y.Z/`:

- `codex-base-X.Y.Z.zip`;
- `release-manifest.json`;
- `components.lock.json`;
- `acceptance-evidence.json`;
- `offline-acceptance-summary.json`.

Candidate manifest связывает evidence; evidence связывает source commit/tree,
ZIP, package manifest и component lock. Stable promotion сохраняет те же ZIP
bytes и требует явный `PASS` каждого release-gate.

Текущий release checkpoint:

- immutable releases включены для будущих GitHub Releases, но tag/release ещё
  не публиковался;
- первый hub canary пакета `0.1.0` обнаружил дефект Foundation rollback;
  предыдущая управляемая поверхность и protected data восстановлены, а пакет
  `0.1.0` запрещён к продвижению;
- исправленный Foundation `0.2.1` и текущий Codex candidate прошли offline
  acceptance, но provider/live canary текущих байтов ещё отсутствует;
- ранее разрешённая четырёхвызовная matched A/B матрица начала первый вызов,
  завершила `0` и остановилась на прежней общей метке `tool_event`; offline
  разбор доказал только семейство `item.*`, потому что runner не сохранял
  subtype. Остальные вызовы не выполнялись, `repeat_authorized=false`;
- runner теперь сохраняет только whitelist `event_type`/`item_type`/category
  и различает tool/workflow/protocol/unknown, не сохраняя payload. Эти
  release-tooling файлы не входят в candidate ZIP, поэтому accepted bytes не
  изменились. До возможного повтора нужен reviewed clean commit runner-а и
  новое явное разрешение владельца;
- stable release и employee rollout остаются заблокированы до всех release
  gates;
- принятые client/package/canary для `claude-base-v2` и `opencode-base` пока
  отсутствуют.

Поэтому `FULL_RELEASE_CODEX` остаётся `NOT_PASS`, а общий program verdict —
`0/3`.
"""
    (docs / "RELEASE-STATUS.md").write_text(
        status, encoding="utf-8", newline="\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
