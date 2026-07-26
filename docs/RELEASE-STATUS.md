# Release status

Candidate ZIP SHA-256: `545c0f80b0c3de4785f8a75022c014729b1561727e5bbe253e3f0848bce973f2`.

| Gate | Verdict |
| --- | --- |
| `FOUNDATION_SYNTHETIC` | `PASS` |
| `CANDIDATE_OFFLINE` | `PASS` |
| `MATCHED_AB` | `NOT_RUN` |
| `CODEX_CANARY` | `NOT_RUN` |
| `FULL_RELEASE_CODEX` | `NOT_PASS` |
| `PROGRAM_RELEASE` | `0/3` |

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
