---
name: sync-base
description: Use only when the user explicitly asks to verify and install a Codex-base release.
---

# sync-base

This is the native one-way Codex-base updater. `$sync-base` is the canonical
invocation; `/sync-base` in user text is a recognized alias.

Run:

```powershell
python "$HOME\.agents\skills\sync-base\tools\sync_base.py"
```

The tool must:

1. select the latest stable, non-prerelease `codex-vX.Y.Z` release;
2. run `gh release verify` before downloading;
3. download all declared release assets;
4. run `gh release verify-asset` for every downloaded asset;
5. validate release manifest, SHA-256 values, target and acceptance verdict;
6. invoke the pinned Foundation engine for `plan`, `install`, and `doctor`;
7. rely on Foundation automatic rollback if install or doctor fails.

Do not install `gh`, log in, change authentication, use a prerelease, downgrade,
or bypass verification. If a prerequisite is absent, return `BLOCKED` with the
exact missing command. Consumers never upload feedback, telemetry, reports, or
local changes.
