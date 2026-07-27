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
- исправленный Foundation `0.2.1` и новый Codex candidate требуют fresh
  offline acceptance и повторного обратимого canary;
- ровно четыре matched A/B вызова GPT-5.6 Terra разрешены, но ещё не
  выполнены; `tools/run_matched_ab.py` по умолчанию работает как dry-run,
  блокирует tools и останавливает матрицу при tool-event либо
  `input_tokens > 100000`;
- stable release и employee rollout остаются заблокированы до всех release
  gates;
- принятые client/package/canary для `claude-base-v2` и `opencode-base` пока
  отсутствуют.

Поэтому `FULL_RELEASE_CODEX` остаётся `NOT_PASS`, а общий program verdict —
`0/3`.
