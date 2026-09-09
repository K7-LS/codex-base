# Engine acceptance for the professional core

`foundation-engine-isolated-v1` is the current engine-only proof. It does not
rename a partial run of the historical full Foundation acceptance suite.
Its producer records `FOUNDATION_ENGINE_ACCEPTANCE: PASS` only after actual
execution; `FOUNDATION_SYNTHETIC` and `INSTALLER_ACCEPTANCE` stay `NOT_RUN`.

The producer records the installer source commit/tree and SHA-256 inventories
for VERSION, APP_VERSION, client-sources.lock.json, src, tests and tools. It
runs syntax checks and builds in PowerShell 7 and 5.1. Both builds must contain
the same version-specific files. Engine 0.5.11 requires nine: VERSION,
engine-manifest.json, foundation.ps1, shared-tools.lock.json and the five locked
OfficeCLI payloads. Engine 0.5.12 requires thirteen: those nine plus
foundation-toml.ps1, vendor/tomlyn/Tomlyn.dll, vendor/tomlyn/LICENSE.txt and
vendor/tomlyn/provenance.json. Unknown versions are rejected. The selected test
list contains seven modules for 0.5.11 and nine for 0.5.12, including both doctor
regression modules.

Each shell must execute fresh install/rollback, existing install/rollback,
late-failure rollback, interrupted recovery, snapshot-tamper rejection,
receipt-drift rejection and foreign-generation rejection. Every scenario
has its own raw command receipt, engine hashes and before/after hashes of
the three real User environment values that installation could affect.
Only synthetic homes are allowed; model requests and real consumer/GUI
execution must be zero. Use short test paths on Windows PowerShell 5.1;
success there does not establish support for arbitrary long paths.

`foundation_artifacts` embeds the original UTF-8 JUnit and receipt bytes,
indexed by SHA-256. The collector only reads declared files beneath the
explicit evidence directory, rejects reparse points and limits the total
bundle to 4 MiB. The final proof remains portable without retaining absolute
machine paths as file dependencies. The engine proof's own body hash is
preserved rather than recomputed to incorporate copied artifacts.

The candidate builder verifies the proof against the actual engine directory.
Final composition and promotion verify it against the engine files under
`.codex/base/foundation/<engine-version>/` inside the exact candidate ZIP.
Current consumer policy requires this protocol and manifest binding. It also
retains the separate package-bound behavior and native canary requirements.

Hashes and schema checks make evidence inspectable and bind it to bytes;
they cannot authenticate execution by themselves. Independent review must
examine the actual test runs and receipts before acceptance. Unit-test proof
fixtures are synthetic and are never release evidence. Offline PASS neither
accepts model behavior nor authorizes publication or installation in a real
profile. Post-publication integrity remains a separate required gate.
