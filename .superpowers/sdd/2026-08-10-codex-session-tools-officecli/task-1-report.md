# Task 1 — provenance/import report

## Scope

- Imported `ru-writing-style` from the approved local source only.
- Kept OfficeCLI as `cold/memory/reference_officecli.md` only.
- Did not install an OfficeCLI binary, MCP server, plugin, or touch `~/.codex`.

## RED evidence

Command:

```powershell
python -m pytest -q tests/test_catalog.py tests/test_repository_contract.py
```

Result on `faa35dc`: `4 failed, 12 passed`.

- `ru-writing-style` was absent from the capability catalog.
- The native tree held `37`, not `38`, skill entrypoints.
- Cold memory held `19`, not `20`, records.
- The exact-source test raised `FileNotFoundError` for
  `skills/ru-writing-style/SKILL.md`.

## Required cherry-pick and provenance failure

- Cherry-picked `e1ba28a` as `35381f34af3da21aa14b6a8c72629a6bcbf5db5c`.
- Re-ran the focused provenance test after the cherry-pick.
- It failed as expected: imported `SKILL.md` was `19264` bytes, while the
  approved source contract requires `20003` bytes.

## Implemented files

- `skills/ru-writing-style/SKILL.md` — replaced with the approved source bytes.
- `catalog/skills.json`, `catalog/cold.json`, `MIGRATION-SOURCE.json` — imported
  by the required cherry-pick; contain 38 capability skills, 20 cold memory
  records, and the OfficeCLI cold reference.
- `cold/memory/reference_officecli.md` — cold reference only, imported by the
  required cherry-pick.
- `tests/test_catalog.py`, `tests/test_repository_contract.py` — count and
  provenance contracts; the latter binds byte size, SHA-256, and OfficeCLI
  placement.
- `tools/generate_docs.py` — derives agent and capability-skill counts from the
  catalog instead of hardcoding `37`.
- `docs/CODEX-CAPABILITIES.md`, `docs/INSTALL-AND-NETWORK.md`, and
  `reports/static-token-audit.json` — regenerated.

The catalog keeps the short WARM discovery description for `ru-writing-style`.
The skill's approved frontmatter is intentionally longer; the repository
contract verifies the immutable source bytes instead of duplicating that long
text into discovery metadata.

## GREEN evidence

Regeneration:

```powershell
python tools/generate_docs.py
```

Focused verification:

```powershell
python -m pytest -q tests/test_catalog.py tests/test_repository_contract.py tests/test_token_audit.py
```

Output: `19 passed`.

Additional checks:

```text
sha256=a20f25a852eaff976c9db90929c94f5658acb3a71eb264479f6d354e04a10938
bytes=20003
byte_equal_source=True
cold-memory=20
contains-officecli=True
skills=38
contains-writing=1
migration-skills=38
migration-cold=26
git diff --check: clean
```

## Commits

- Required import commit: `35381f34af3da21aa14b6a8c72629a6bcbf5db5c`
  (`feat: add approved Russian writing skill and OfficeCLI reference`).
- Approved-source correction: `552dca40f7f2722aff0385bfa155d47b39948a02`
  (`fix: enforce approved ru-writing-style provenance`).

## Concerns

- No release build, Foundation validation, session updater, OfficeCLI command
  smoke, or live canary ran; they are outside Task 1.
- The imported OfficeCLI material is documentation only and remains cold. Its
  binary and automatic installation are intentionally absent.
