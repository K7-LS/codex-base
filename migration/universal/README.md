# Universal sync-base migration

This bridge is for installations whose historical $sync-base cannot accept
the current release evidence format. It selects the latest immutable stable
codex-vX.Y.Z release from K7-LS/codex-base, starting at 0.2.3. It has no fixed
Codex CLI or Desktop version. An already installed newer Base is never
downgraded. The bridge does not change the user's model or reasoning settings.

The bridge is distributed separately as sync-base-migration-v1.0.1.
The first eligible Base release, 0.2.3, uses `installation-integrity-v1`:
offline checks, Foundation and a no-model canary support installation and
update. It does not claim professional model-behavior acceptance;
`CORE_BEHAVIOR` remains `NOT_RUN` and `FULL_RELEASE_CODEX` remains `NOT_PASS`.
Before executing any downloaded script, verify that immutable release with
gh release verify, download its ZIP and manifest, run gh release verify-asset
and gh attestation verify for both, and compare the ZIP SHA-256 and byte count
with migration-release-manifest.json. Verify all three entries inside the ZIP
against that manifest. A local checkout or unsigned file is not a release.

Use a new empty staging directory and stop on any nonzero command:

    $repo = 'K7-LS/codex-base'
    $tag = 'sync-base-migration-v1.0.1'
    $stage = 'C:\path\to\new-empty-stage'
    $ErrorActionPreference = 'Stop'
    function Invoke-CheckedGh {
        param([string[]]$Arguments)
        $output = & gh @Arguments
        if ($LASTEXITCODE -ne 0) { throw ('gh failed: ' + ($Arguments -join ' ')) }
        return $output
    }
    $releaseJson = Invoke-CheckedGh @('release', 'view', $tag, '-R', $repo,
        '--json', 'tagName,isDraft,isPrerelease,isImmutable')
    $release = $releaseJson | ConvertFrom-Json
    if ($release.tagName -cne $tag -or $release.isDraft -ne $false -or
        $release.isPrerelease -ne $false -or $release.isImmutable -ne $true) {
        throw 'Bridge release is not immutable stable'
    }
    Invoke-CheckedGh @('release', 'verify', $tag, '-R', $repo) | Out-Null
    Invoke-CheckedGh @('release', 'download', $tag, '-R', $repo, '--dir', $stage) | Out-Null
    foreach ($name in @('migration-release-manifest.json', 'sync-base-migration-1.0.1.zip')) {
        $file = Join-Path $stage $name
        Invoke-CheckedGh @('release', 'verify-asset', $tag, $file, '-R', $repo) | Out-Null
        Invoke-CheckedGh @('attestation', 'verify', $file, '--repo', $repo) | Out-Null
    }

Check the manifest and every archive member before writing any executable file:

    $manifest = Get-Content (Join-Path $stage 'migration-release-manifest.json') -Raw | ConvertFrom-Json
    $zipFile = Join-Path $stage 'sync-base-migration-1.0.1.zip'
    $zipBytes = [IO.File]::ReadAllBytes($zipFile)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $zipDigest = -join ($sha.ComputeHash($zipBytes) | ForEach-Object { $_.ToString('x2') }) }
    finally { $sha.Dispose() }
    if ($manifest.target -cne 'codex' -or $manifest.tag -cne $tag -or
        $manifest.status -cne 'RELEASE_PREPARED' -or
        $manifest.asset.name -cne 'sync-base-migration-1.0.1.zip' -or
        $manifest.asset.bytes -ne $zipBytes.Length -or
        $manifest.asset.sha256 -cne $zipDigest) {
        throw 'Migration release manifest or ZIP differs'
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zipFile)
    try {
        $expected = @('README.md', 'connection.ps1', 'migrate-sync-base.ps1')
        $actual = @($archive.Entries | ForEach-Object { $_.FullName } | Sort-Object)
        if (($actual -join '|') -cne (($expected | Sort-Object) -join '|')) { throw 'Archive entries differ' }
        $expanded = Join-Path $stage 'verified-bridge'
        New-Item -ItemType Directory -Path $expanded -ErrorAction Stop | Out-Null
        $payloads = @{}
        foreach ($name in $expected) {
            $entry = $archive.GetEntry($name)
            $row = @($manifest.files | Where-Object { $_.path -ceq $name })
            if ($row.Count -ne 1) { throw 'File manifest differs' }
            $stream = $entry.Open()
            $memory = New-Object IO.MemoryStream
            try { $stream.CopyTo($memory); $bytes = $memory.ToArray() }
            finally { $memory.Dispose(); $stream.Dispose() }
            $sha = [Security.Cryptography.SHA256]::Create()
            try { $digest = -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) }
            finally { $sha.Dispose() }
            if ($bytes.Length -ne $row[0].bytes -or $digest -cne $row[0].sha256) { throw 'File bytes differ' }
            $payloads[$name] = $bytes
        }
        foreach ($name in $expected) { [IO.File]::WriteAllBytes((Join-Path $expanded $name), $payloads[$name]) }
    }
    finally { $archive.Dispose() }

Extract only after those checks. The bridge
then independently verifies the latest Base release, all five Base assets and
their attestations. It extracts only the signed updater and policy, verifies
package inventory, then asks Foundation for an interactive plan. Foundation
makes the backup, applies the package, runs doctor and rolls back if doctor
fails. Verify performs no installation; Plan writes a plan in a new staging
directory; Install executes the verified workflow.

    & (Join-Path $expanded 'migrate-sync-base.ps1') -Mode Verify -WorkDirectory 'C:\path\to\new-verify-stage'
    & (Join-Path $expanded 'migrate-sync-base.ps1') -Mode Plan -WorkDirectory 'C:\path\to\new-plan-stage'
    & (Join-Path $expanded 'migrate-sync-base.ps1') -Mode Install -WorkDirectory 'C:\path\to\new-install-stage'

Use a distinct, absent staging directory for each run, outside .codex,
.agents and .llm-foundation. Each mode fetches and verifies the current stable
release afresh. A plan from an earlier release is not reused. User
credentials, sessions, local changes and reports are not uploaded.
