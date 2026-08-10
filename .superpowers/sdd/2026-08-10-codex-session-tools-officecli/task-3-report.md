# Task 3 report — Codex session-tools runtime

## Scope

- Added the Codex session-tools updater and its SessionStart fallback hook.
- Added durable protocol-1 apply/recovery with the same journal contract as the managed launcher.
- Added runtime tests for PowerShell 7 and Windows PowerShell 5.1, including Cyrillic paths without `PYTHONIOENCODING`.
- Did not publish a release, change live user directories, install OfficeCLI, or mutate plugin/MCP configuration.

## Runtime contract

- Target: `codex`; repository: `daniileliseev1337/codex-base`.
- State: `%USERPROFILE%/.llm-foundation/state/session-tools/codex/state.json`.
- Journal: `%USERPROFILE%/.llm-foundation/state/session-tools/codex/active-transaction.json`.
- Baseline: `%USERPROFILE%/.codex/base/runtime/session-tools-baseline.json`.
- Destination: `%USERPROFILE%/.agents/skills/ru-writing-style`.
- Trust chain: stable semver tag, `gh release verify`, `verify-asset` and attestation for the release manifest and session asset, strict release/session binding, SHA-256 and byte verification.
- Clock: one launcher receipt with monotonic 22/25/30-second cutoffs; journal is durable before staging and recovery uses actual filesystem fingerprints.
- Recovery parity source: Foundation managed launcher commit `0b18718b224a64b2055748aab0ea3406be92aa2d`.

Protocol `1` accepts exactly one tool. Zero or multiple tools return `BLOCKED_MULTI_TOOL_ASSET` before mutation. This is an intentional runtime limitation until the journal protocol is upgraded.

## TDD evidence

### RED

The first focused test failed because `runtime/update-session-tools.ps1` did not exist. Additional focused RED checks then demonstrated that the incomplete implementation:

- accepted empty release `verification_commands` and installed the asset;
- deleted a regular file placed at the exact created-phase staging path;
- accepted a receipt after the managed launcher bytes were changed;
- wrote a filesystem exception containing the user profile path to `update.log`.
- skipped the existing daily base check when the updater emitted its notice;
- accepted a negative `bytes` value in current ownership state;
- converted `verified_at` to local `DateTime` on PowerShell 7 and mislabeled a valid no-op as state drift.

Each case was fixed only after its failing test was observed.

### GREEN

```powershell
python -m pytest -q tests/test_session_tools_runtime.py
# 35 passed in 86.8s

python -m pytest -q tests/test_update_runtime.py
# 32 passed in 12.8s

python -m pytest -q tests/test_session_tools_release.py
# 17 passed in 59.0s
```

The runtime suite exercised `pwsh.exe` 7.6.4 and Windows PowerShell 5.1. It covers strict duplicate-aware UTF-8 JSON, strict ZIP paths/modes/limits, exact-one-tool enforcement, immutable release commands, baseline/state ownership, no-op, collision, missing/offline `gh`, bounded lock, deadline, killed-phase recovery, partial staging, regular-file staging, nested reparse containment, receipt tamper and hook output.

## Hook behavior

- Managed launch applies the verified tool before the vendor process and therefore supports same-session discovery.
- Direct vendor launch is only a fallback. The hook emits at most one `TOOLS_APPLIED_NEXT_SESSION` system message after an apply and does not claim same-session discovery.
- Existing base-release notification behavior remains after the updater fallback.

## Independent review

The first read-only review found three Important issues and no Critical issues:

- updater success bypassed the existing daily base-release check;
- created-phase cleanup reused a helper that could delete a regular-file leaf;
- current state file records did not validate paths, ordering and actual byte counts.

All three were reproduced or pinned by focused tests and fixed. The follow-up also added a cross-host no-op assertion that exposed and fixed PowerShell 7 date auto-conversion.

The independent re-review returned `READY` with no Critical or Important issues. It ran 10 focused tests, a Windows PowerShell 5.1 to PowerShell 7 no-op probe and a PowerShell 7 to Windows PowerShell 5.1 actual-bytes-drift probe; all passed.

## Concerns

- The tests use a local fake `gh`; no live stable release, GitHub attestation service, or publication path was exercised.
- This task is a scoped runtime implementation result, not a full release PASS.
- Protocol `1` remains intentionally limited to one session tool.
