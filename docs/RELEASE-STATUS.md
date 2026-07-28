# Release status

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
