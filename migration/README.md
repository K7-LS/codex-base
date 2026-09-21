# Official sync-base protocol migration

This is an explicit, one-time path from historical Codex Base installations to
the already accepted, immutable `codex-v0.2.2`. It does not create a new base ZIP
or reinterpret historical acceptance results. It preserves the target release's
`FOUNDATION_SYNTHETIC=NOT_RUN`, `MATCHED_AB=NOT_REQUIRED` and
`PROGRAM_RELEASE=1/3`.

An unchanged historical `$sync-base` cannot perform this transition: it requires
the first two fields to be `PASS`, while the current verifier requires their
published values. No single truthful evidence file satisfies both consumers.
The separate tag `sync-base-migration-v1.0.0` is intentionally outside the normal
`codex-vX.Y.Z` update selector. This is a migration release, not transparent
backward compatibility of the old command.

## Trust before execution

Obtain the migration only from an immutable stable release in
`K7-LS/codex-base`. **Verify the migration release and both downloaded assets
before extracting or executing any script.** Checking a script after starting
it is not a trust boundary. Do not download and execute a script from `main`,
change an installed policy manually, or skip an unavailable verification.
The following procedure is usable only after the migration release is published;
an unpublished local candidate is for review and isolated tests.

Use the existing approved GitHub connection and `gh` login. Do not install tools,
change authentication, or expose proxy credentials to make these commands pass.
Every native exit code must be checked:

```powershell
$ErrorActionPreference = 'Stop'
$migrationTag = 'sync-base-migration-v1.0.0'
$migrationRepo = 'K7-LS/codex-base'
$releaseJson = & gh release list -R $migrationRepo --limit 100 --json tagName,isDraft,isPrerelease,isImmutable
if ($LASTEXITCODE -ne 0) { throw 'Release discovery failed' }
$listedReleases = $releaseJson | ConvertFrom-Json
$published = @($listedReleases | Where-Object { $_.tagName -ceq $migrationTag })
if ($published.Count -ne 1 -or $published[0].isDraft -ne $false -or
    $published[0].isPrerelease -ne $false -or $published[0].isImmutable -ne $true) {
    throw 'Migration is not an immutable stable release'
}
& gh release verify $migrationTag -R $migrationRepo
if ($LASTEXITCODE -ne 0) { throw 'Migration release verification failed' }
$downloadDirectory = Join-Path (Get-Location) 'sync-migration-download'
if (Test-Path -LiteralPath $downloadDirectory) { throw 'Choose a new download directory' }
New-Item -ItemType Directory -Path $downloadDirectory | Out-Null
& gh release download $migrationTag -R $migrationRepo --dir $downloadDirectory
if ($LASTEXITCODE -ne 0) { throw 'Migration download failed' }
$migrationAssets = @(Get-ChildItem -LiteralPath $downloadDirectory -File | Sort-Object Name)
if (($migrationAssets.Name -join '|') -cne 'migration-release-manifest.json|sync-base-migration-1.0.0.zip') {
    throw 'Migration asset set differs'
}
foreach ($asset in $migrationAssets) {
    & gh release verify-asset $migrationTag $asset.FullName -R $migrationRepo
    if ($LASTEXITCODE -ne 0) { throw 'Migration asset verification failed' }
    & gh attestation verify $asset.FullName --repo $migrationRepo
    if ($LASTEXITCODE -ne 0) { throw 'Migration asset attestation failed' }
}
$expanded = Join-Path $downloadDirectory 'verified'
Expand-Archive -LiteralPath (Join-Path $downloadDirectory 'sync-base-migration-1.0.0.zip') -DestinationPath $expanded
```

## Verify, plan, install

The default mode only downloads, verifies and extracts into a new staging
directory. It does not write to the target profile or run Foundation install.
The bundled connection runtime reads the saved Direct, VPN, HTTP, HTTPS or SOCKS5
profile and restores the process environment after network operations.

```powershell
& (Join-Path $expanded 'migrate-sync-base.ps1') -WorkDirectory (Join-Path (Get-Location) 'migration-verify')
```

Use a **different, new staging directory on each run**. Each mode repeats online
verification; an old `VERIFIED` result never authorizes a later install. Staging
must be outside `.codex`, `.agents` and `.llm-foundation` in the target home.

```powershell
& (Join-Path $expanded 'migrate-sync-base.ps1') -Mode Plan -WorkDirectory (Join-Path (Get-Location) 'migration-plan')
& (Join-Path $expanded 'migrate-sync-base.ps1') -Mode Install -WorkDirectory (Join-Path (Get-Location) 'migration-install')
```

Run `Install` only when the owner requested the protocol migration and installation.
The migration verifies the signature, Actions attestation and exact SHA-256/size
of **all five** base release assets. It loads the updater and policy together
from that verified ZIP and runs its unchanged acceptance verifier. Plan and
Install require the actually detected `codex-cli 0.153.1`, an existing Foundation
base state, and a lower installed base version. A newer installed version is
rejected; an equal version is a no-op. A newer stable base in the hub requires a
reviewed migration pin update rather than silently using this old target.

Foundation performs inventory, interactive plan, backup/apply, doctor and
rollback if the post-install doctor fails. No updater files are copied into the
profile ahead of that transaction. Local exceptions still need the normal
Foundation decisions. A narrow output adapter separates echoed `KEEP`/`REMOVE`
answers from the engine's single JSON plan and checks its package/home/client
binding before passing the unchanged plan to apply. Extra or ambiguous output
is rejected. After success, fully restart Codex and run the installed
Foundation `doctor -Strict`. Subsequent updates use the installed `$sync-base`.

Authentication, sessions, client memories and user model/reasoning choices remain
under the existing Foundation preservation contract. Missing `gh`, PowerShell,
the tested client version, valid state, signatures or evidence stop the dependent
operation. The migration does not install prerequisites or contact an upload API.

## Hub preparation and acceptance scope

```powershell
python -m pytest tests/test_sync_migration.py tests/test_sync_powershell.py -q
python tools/build_sync_migration.py --output dist/sync-base-migration-v1.0.0
```

The builder makes two local assets, never publishes, and records source dirtiness
truthfully. Review the final bytes and commit the reviewed source before preparing
publication assets from a clean checkout. Publish both assets under the separate
immutable stable migration tag only after owner authorization. The existing
`Attest release assets` workflow must finish before consumer distribution;
independently rerun release, per-asset and Actions verification after publication.

Transport mocks and synthetic homes in unit tests prove orchestration and refusal
boundaries, not actual GitHub signatures or every historical installation. Fresh
online Verify checks and isolated real-engine migration/rollback rehearsals are
separate evidence. Never label untested historical families or a real workstation
installation as accepted. The underlying behavioral evidence remains bound to
the original base ZIP, not to this wrapper or a rebuilt base package.
