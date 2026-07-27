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
py -3.12 -m pip install pytest PyYAML
$env:PYTHONPATH = "src"
py -3.12 -m pytest -q
py -3.12 .\tools\run_acceptance.py `
  --foundation ..\llm-foundation-installer\.work\acceptance\engine-ps7 `
  --foundation-evidence ..\llm-foundation-installer\dist\foundation-acceptance.json
```

Acceptance refuses a dirty worktree. Candidate bytes are exported from the
recorded Git commit/tree; ZIP, package manifest, component lock and evidence
are cross-bound by SHA-256. The updater extracts and runs only the exact
Foundation engine inside that verified ZIP.

The resulting candidate remains fail-closed:

- `MATCHED_AB: NOT_RUN`
- `CODEX_CANARY: NOT_RUN`
- `FULL_RELEASE_CODEX: NOT_PASS`

The owner has authorized exactly one guarded four-call GPT-5.6 Terra
matched A/B, one live hub canary, push, and immutable release publication.
They have not run yet. Any A/B repeat or expansion requires new approval.

Review the no-spend plan before the paid run:

```powershell
py -3.12 .\tools\run_matched_ab.py
```

After those gates produce final `PASS` evidence, stable assets can be prepared
without rebuilding the ZIP:

```powershell
py -3.12 .\tools\promote_candidate.py `
  --candidate .\dist\candidate-0.1.1 `
  --final-evidence <approved-final-evidence.json> `
  --output .\dist\stable-0.1.1
```

This command does not publish to GitHub.

After immutable publication, the local package is not accepted merely because
its checksum matches. The verifier requires stable, non-draft, immutable
GitHub state plus successful release and asset attestations:

```powershell
py -3.12 .\tools\verify_release.py `
  --manifest .\dist\stable-0.1.1\release-manifest.json `
  --asset .\dist\stable-0.1.1\codex-base-0.1.1.zip `
  --output .\dist\stable-0.1.1\release-verification.json

py -3.12 .\tools\create_package_acceptance.py `
  --manifest .\dist\stable-0.1.1\release-manifest.json `
  --evidence .\dist\stable-0.1.1\acceptance-evidence.json `
  --release-verification .\dist\stable-0.1.1\release-verification.json `
  --output .\dist\stable-0.1.1\package-acceptance.json
```

`package-acceptance.json` is created only after publication and is the record
the employee installer consumes.
