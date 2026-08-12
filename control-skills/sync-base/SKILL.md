---
name: sync-base
description: Use only when the user explicitly asks to verify and install a Codex-base release.
---

# sync-base

This is the native one-way Codex-base updater. `$sync-base` is the canonical
invocation; `/sync-base` in user text is a recognized alias.

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  "$HOME\.agents\skills\sync-base\tools\sync_base.ps1" `
  -PolicyPath "$HOME\.agents\skills\sync-base\sync-policy.json"
```

The tool must:

1. select the latest stable, non-prerelease `codex-vX.Y.Z` release;
2. download the package and its release manifest;
3. validate target, version and the package SHA-256 from the manifest;
4. invoke the packaged Foundation engine for `plan`, `install`, and `doctor`;
5. invoke Foundation `rollback` if install succeeds but doctor fails;
6. use the saved Direct, VPN, HTTP, HTTPS, or SOCKS5 connection profile
   without writing credentials to logs or command history.

Do not install `gh`, log in, change authentication, use a prerelease, or downgrade.
If a prerequisite is absent, return `BLOCKED` with the
exact missing command. Consumers never upload feedback, telemetry, reports, or
local changes.
