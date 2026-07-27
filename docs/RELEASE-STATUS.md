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

Не проверено и не разрешено:

- paid matched A/B на Terra/Sol;
- изменение текущего `~/.codex`;
- hub canary;
- stable GitHub Release и immutable/asset attestation на опубликованном tag;
- employee rollout;
- принятые client-version, package acceptance и canary для реализованных
  `claude-base-v2` и `opencode-base`.

Поэтому `FULL_RELEASE_CODEX` остаётся `NOT_PASS`, а общий program verdict —
`0/3`.
