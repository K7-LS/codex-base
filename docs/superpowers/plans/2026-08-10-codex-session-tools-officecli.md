# Codex Session Tools and OfficeCLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Use superpowers:test-driven-development for production changes, superpowers:writing-skills for the skill deployment test, and superpowers:verification-before-completion before commits.

**Goal:** подготовить Codex Base `0.1.4`, который доставляет `ru-writing-style` через проверяемый session auto-pull и OfficeCLI через Foundation `0.3.0`, сохраняя локальные skills и старый `$sync-base` bootstrap.

**Architecture:** repository skill остаётся source/catalog record. Release builder исключает его из обычного package ownership, создаёт immutable `session-tools-codex-0.1.4.zip` и package baseline. Managed launcher запускает target updater до Codex process; SessionStart остаётся fail-open fallback. OfficeCLI bytes копируются только из принятого Foundation release и устанавливаются Foundation transaction.

**Tech Stack:** Python 3.12 + pytest, PowerShell 7/5.1, GitHub release/attestation CLI, Foundation protocol 1.

## Global Constraints

- Audited design: `C:/Users/Даниил/repos/llm-foundation-installer/.worktrees/auto-tools-officecli/docs/superpowers/specs/2026-08-10-session-tools-officecli-design.md` at `394999c`.
- Start from `origin/main` `c79e27ea8674cf26e02b2f94f0c715b7ca8a3639` and reuse feature commit `e1ba28a` only after RED contract tests.
- Approved live skill source: `C:/Users/Даниил/.claude/skills/ru-writing-style/SKILL.md`, SHA-256 `a20f25a852eaff976c9db90929c94f5658acb3a71eb264479f6d354e04a10938`, 20003 bytes.
- Require an independently accepted immutable Foundation `0.3.0` release before building the target candidate.
- Preserve user config/auth/history/plugins/projects and every unmanaged skill. Do not auto-push.
- Keep direct vendor launch fail-open; claim same-session availability only through `codex-managed.exe`/Launch Center until a live direct-discovery canary proves more.
- Do not publish automatically.

## File Map

- `skills/ru-writing-style/SKILL.md`, `cold/memory/reference_officecli.md`, `catalog/*.json`, `MIGRATION-SOURCE.json` — source and catalogs.
- `src/codex_base/session_tools.py` — deterministic session asset/baseline builder.
- `src/codex_base/release.py`, `acceptance.py`, `promotion.py`, `release_verification.py` — package and release binding.
- `runtime/update-session-tools.ps1`, `runtime/hooks.json`, `runtime/hooks/check_release.ps1` — updater and fallback.
- `tests/test_session_tools.py`, `tests/test_session_tools_runtime.py`, `tests/test_release_contract.py`, `tests/test_sync_powershell.py` — contracts.
- `tools/run_acceptance.py`, `tools/run_live_canary.py`, `src/codex_base/canary.py`, `final_evidence.py` — acceptance.

---

### Task 1: RED skill provenance, then import approved source

- [ ] Add RED tests in `tests/test_catalog.py` and `tests/test_repository_contract.py` for 38 capability skills, 20 cold-memory records, exact `ru-writing-style` SHA-256/size and OfficeCLI cold reference. Run focused tests and record failures.
- [ ] Cherry-pick `e1ba28a`; confirm provenance test still fails because its skill bytes are older than the approved live source.
- [ ] Replace only `skills/ru-writing-style/SKILL.md` with the approved source bytes, update catalog/migration records, and fix `tools/generate_docs.py` to derive counts rather than hardcode `37`.
- [ ] Regenerate docs/report and run `python -m pytest -q tests/test_catalog.py tests/test_repository_contract.py tests/test_token_audit.py`. Commit `feat: add approved Russian writing skill and OfficeCLI reference`.

### Task 2: Deterministic session asset and package baseline

- [ ] Add RED `tests/test_session_tools.py`: strict duplicate-aware manifest parsing; deterministic UTF-8 LF ZIP; Windows case collisions; traversal/absolute/symlink/executable rejection; limits 32 tools, 256 files, 1 MiB/file, 8 MiB expanded, 10 MiB ZIP; tampered hashes/bytes.
- [ ] Implement `src/codex_base/session_tools.py` with `SessionToolsBuild` and `build_session_tools_bundle(..., tool_ids=("ru-writing-style",))`.
- [ ] Add RED release tests for `session_tools_asset`, `session_tools_baseline`, exclusion from normal target files and granular `.agents/skills/<id>` ownership including `sync-base` but excluding `ru-writing-style`.
- [ ] Modify `src/codex_base/release.py` and `acceptance.py`; keep old manifests readable. Run focused tests to GREEN. Commit `feat: build Codex session tool assets`.

### Task 3: Session updater and direct fallback

- [ ] Add RED `tests/test_session_tools_runtime.py` with fake `gh` for immutable stable release, `verify-asset`, attestation, strict manifest validation, state/baseline recovery, unmanaged collision, no-op/update, offline/missing-gh/lock/deadline, killed phases and Cyrillic without `PYTHONIOENCODING`.
- [ ] Implement `runtime/update-session-tools.ps1` with one launcher clock contract, durable journal before staging, atomic apply/recovery and a maximum one fallback line.
- [ ] Update `runtime/hooks/check_release.ps1` to call the same updater with `-HookFallback` before the existing daily version check; update `runtime/hooks.json` without claiming same-session direct discovery.
- [ ] Run focused runtime tests in PowerShell 7 and 5.1. Commit `feat: update Codex session tools before launch`.

### Task 4: Accepted Foundation shared tools and old sync compatibility

- [ ] Add RED tests that `_validate_foundation` requires Foundation `0.3.0` release manifest, package acceptance and exact OfficeCLI/shim/policy/launcher bytes; reject tamper or source-binding mismatch.
- [ ] Extend release/promotion/verifier tools to bind main ZIP, session ZIP and release manifest; require `gh release verify-asset` plus `gh attestation verify` for every published asset.
- [ ] Add RED homes for clean, legacy broad, and broad-plus-local skill; run the actually shipped legacy `$sync-base` fixture against protocol-1 package fields. Preserve local skill byte-for-byte through install/doctor/rollback.
- [ ] Update `tests/support/sync_base_reference.py` to compare the required subset while accepting new optional fields. Run `tests/test_release_contract.py`, `test_sync_powershell.py`, `test_release_verification.py`, `test_promotion.py`, `test_acceptance.py`. Commit `feat: bind Codex package to Foundation shared tools`.

### Task 5: Counts, acceptance and managed-launch canary

- [ ] Update computed expectations: 16 agents, 38 capability skills, 1 control skill, 20 cold-memory records, 26 cold total; clean discovery 39 and broad-plus-local discovery 40.
- [ ] Add RED canary/final-evidence tests requiring `codex-managed.exe`, updater tag/hash/result and `ru-writing-style` present before Codex process discovery. Provider unavailable remains `NOT_PASS`.
- [ ] Update `tools/run_acceptance.py`, matched A/B, canary, final evidence and generated reports. Keep release status fail-closed until actual live/immutable gates.
- [ ] Run all focused acceptance/evidence tests to GREEN. Commit `test: bind Codex acceptance to managed session tools`.

### Task 6: Full candidate verification

- [ ] Run `python -m pytest -q`, regenerate docs/reports, and require `git diff --exit-code -- docs reports`.
- [ ] Build candidate `0.1.4` against accepted Foundation `0.3.0`; run offline acceptance in PowerShell 7 and 5.1 and existing-install legacy `$sync-base` migration.
- [ ] Run isolated `codex-managed.exe` canary and verify same-session discovery, OfficeCLI normal document command smoke and blocked self-management snapshots.
- [ ] Run independent whole-branch review. Keep candidate unpublished and every absent provider/immutable gate `NOT_PASS`.

## Plan Self-Review

- Exact provenance and counts are bound; session and package ownership do not overlap.
- Old `$sync-base`, unmanaged skills and direct fallback have explicit tests.
- No publication, auth/session/plugin/MCP mutation or auto-push is authorized by this plan.
