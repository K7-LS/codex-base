# Codex Base

Native, progressively loaded base for `codex-cli 0.146.0-alpha.3.1`.

## Runtime shape

- HOT: compact global `AGENTS.md` on every new session.
- WARM: discovery metadata for 16 domain agents, 37 capability skills, and
  one explicit control skill (`sync-base`).
- COLD: full skill instructions, scripts, templates, 19 reference files,
  3 named chains, and 3 command references loaded only after routing.

The base does not set a model or reasoning level. Simple conversation must not
invoke tools, custom agents, or reviewers. MCP servers and plugins are not
preconfigured; a selected skill declares the capability it needs and missing
dependencies fail as `BLOCKED`.

## One-way delivery

Consumers only check and receive immutable stable GitHub releases. The
SessionStart hook performs one anonymous GitHub `GET` at most once per day and
is silent when there is no update. Installation is explicit through
`$sync-base`; `/sync-base` remains a text alias.

No consumer feedback, telemetry, session report, credential, or local-change
upload exists.

## Build and offline acceptance

```powershell
$env:PYTHONPATH = "src"
py -3.12 -m pytest -q
py -3.12 .\tools\run_acceptance.py `
  --foundation ..\llm-foundation-installer\dist\foundation-engine-0.1.0 `
  --foundation-evidence ..\llm-foundation-installer\reports\foundation-acceptance.json
```

The resulting candidate remains fail-closed:

- `MATCHED_AB: NOT_RUN`
- `CODEX_CANARY: NOT_RUN`
- `FULL_RELEASE_CODEX: NOT_PASS`

Paid matched A/B, a live hub canary, and stable release publication each need
separate owner approval.
