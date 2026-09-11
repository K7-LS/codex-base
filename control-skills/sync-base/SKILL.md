---
name: sync-base
description: Use for Codex-base release updates or requested Codex context diagnostics and configuration.
---

# sync-base

This is the native one-way Codex-base updater. `$sync-base` is the canonical
invocation; `/sync-base` in user text is a recognized alias.

Choose the requested operation. A request to inspect context settings does not
authorize a release installation. Read [client context](references/client-context.md)
for local diagnostics or an explicitly requested Dynamic-context change. That
helper reports configuration, CLI recognition and unverified runtime levels
separately; it does not run a model. Preserve the user's model and reasoning.

For a release update, run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  "$HOME\.agents\skills\sync-base\tools\sync_base.ps1"
```

The tool must:

1. select the latest stable, non-prerelease `codex-vX.Y.Z` release;
2. run `gh release verify` before downloading;
3. download all declared release assets;
4. run `gh release verify-asset` for every downloaded asset;
5. validate release manifest, SHA-256 values, target and acceptance verdict;
6. invoke the pinned Foundation engine for `plan`, `install`, and `doctor`;
7. invoke Foundation `rollback` if install succeeds but doctor fails;
8. use the saved Direct, VPN, HTTP, HTTPS, or SOCKS5 connection profile
   without writing credentials to logs or command history.

Do not install `gh`, log in, change authentication, use a prerelease, downgrade,
or bypass verification. If a prerequisite is absent, return `BLOCKED` with the
exact missing command. Consumers never upload feedback, telemetry, reports, or
local changes.
