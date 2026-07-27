[CmdletBinding()]
param(
    [string]$PolicyPath = (
        Join-Path (Split-Path -Parent $PSScriptRoot) 'sync-policy.json'
    ),
    [string]$TargetHome = $env:USERPROFILE,
    [switch]$Check,
    [switch]$LibraryMode
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# Allowed remote operations:
# gh release verify
# gh release verify-asset
# gh release download
# gh release list
# gh attestation verify

function Get-LlmSha256Bytes {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Bytes
    )

    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return -join (
            $algorithm.ComputeHash($Bytes) |
                ForEach-Object { $_.ToString('x2') }
        )
    }
    finally {
        $algorithm.Dispose()
    }
}

function Get-LlmSha256File {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )

    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return -join (
            $algorithm.ComputeHash($stream) |
                ForEach-Object { $_.ToString('x2') }
        )
    }
    finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}

function Get-LlmSyncPolicy {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw 'Sync policy is missing.'
    }
    try {
        $policy = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw 'Sync policy JSON is invalid.'
    }
    if ([int]$policy.schema_version -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$policy.target) -or
        [string]$policy.target -notmatch '^[a-z][a-z0-9-]*$' -or
        [string]$policy.repository -notmatch (
            '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'
        ) -or
        [string]$policy.tag_prefix -notmatch '^[a-z][a-z0-9-]*-v$' -or
        [string]$policy.transformation -notmatch (
            '^[a-z][a-z0-9-]*-native-v[0-9]+$'
        ) -or
        [string]$policy.install_root -notmatch (
            '^[.A-Za-z0-9_-]+(?:/[.A-Za-z0-9_-]+)*$'
        ) -or
        $null -eq $policy.client -or
        [string]::IsNullOrWhiteSpace([string]$policy.client.id) -or
        @($policy.client.command).Count -lt 1 -or
        [string]$policy.client.acceptance -notin @(
            'PASS',
            'NOT_ACCEPTED'
        ) -or
        (
            [string]$policy.client.acceptance -ceq 'PASS' -and
            [string]::IsNullOrWhiteSpace(
                [string]$policy.client.version_pattern
            )
        ) -or
        $null -eq $policy.evidence -or
        [string]$policy.evidence.style -notin @('flat', 'verdicts') -or
        @($policy.evidence.required_verdicts).Count -lt 1 -or
        [string]$policy.evidence.program_release -notmatch '^[1-3]/3$') {
        throw 'Sync policy contract is invalid or not accepted.'
    }
    foreach ($value in @($policy.client.command)) {
        if ([string]$value -notmatch '^[A-Za-z0-9_.-]+$') {
            throw 'Sync client command contains an unsafe value.'
        }
    }
    foreach ($value in @($policy.evidence.required_verdicts)) {
        if ([string]$value -notmatch '^[A-Z][A-Z0-9_]*$') {
            throw 'Sync evidence verdict contains an unsafe value.'
        }
    }
    return $policy
}

function Select-LlmStableRelease {
    param(
        [Parameter(Mandatory = $true)]$Releases
    )

    $prefix = [regex]::Escape([string]$script:LlmSyncPolicy.tag_prefix)
    $pattern = '^' + $prefix + '(\d+)\.(\d+)\.(\d+)$'
    $candidates = @()
    foreach ($release in @($Releases)) {
        $tag = [string]$release.tagName
        $match = [regex]::Match($tag, $pattern)
        if (-not $match.Success -or
            [bool]$release.isDraft -or
            [bool]$release.isPrerelease) {
            continue
        }
        $candidates += [pscustomobject]@{
            tag = $tag
            version = New-Object version (
                '{0}.{1}.{2}' -f
                $match.Groups[1].Value,
                $match.Groups[2].Value,
                $match.Groups[3].Value
            )
        }
    }
    if ($candidates.Count -eq 0) {
        throw 'No stable release is available.'
    }
    return [string](
        $candidates |
            Sort-Object -Property version -Descending |
            Select-Object -First 1
    ).tag
}

function Invoke-LlmGh {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $output = & gh @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw (
            'GitHub verification command failed: gh ' +
            ($Arguments[0..([Math]::Min(1, $Arguments.Count - 1))] -join ' ')
        )
    }
    return ($output -join "`n")
}

function Get-LlmLatestStableTag {
    $json = Invoke-LlmGh -Arguments @(
        'release',
        'list',
        '-R',
        [string]$script:LlmSyncPolicy.repository,
        '--limit',
        '100',
        '--json',
        'tagName,isDraft,isPrerelease'
    )
    try {
        $releases = $json | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw 'GitHub release list JSON is invalid.'
    }
    return Select-LlmStableRelease -Releases $releases
}

function Read-LlmZipEntryBytes {
    param(
        [Parameter(Mandatory = $true)]$Archive,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $entries = @($Archive.Entries | Where-Object {
        [string]$_.FullName -ceq $Name
    })
    if ($entries.Count -ne 1) {
        throw "ZIP entry is missing or duplicated: $Name"
    }
    $stream = $entries[0].Open()
    $memory = New-Object IO.MemoryStream
    try {
        $stream.CopyTo($memory)
        return $memory.ToArray()
    }
    finally {
        $memory.Dispose()
        $stream.Dispose()
    }
}

function Assert-LlmReleaseEvidence {
    param(
        [Parameter(Mandatory = $true)]$Evidence,
        [Parameter(Mandatory = $true)]$Manifest,
        [Parameter(Mandatory = $true)][string]$EvidencePath,
        [Parameter(Mandatory = $true)][string]$ManifestPath
    )

    if ([string]$Evidence.target -cne [string]$script:LlmSyncPolicy.target) {
        throw 'Acceptance evidence target differs.'
    }
    $style = [string]$script:LlmSyncPolicy.evidence.style
    $verdictRoot = if ($style -ceq 'flat') {
        $Evidence
    }
    else {
        $Evidence.verdicts
    }
    if ($null -eq $verdictRoot) {
        throw 'Acceptance evidence verdicts are missing.'
    }
    foreach ($name in @(
        $script:LlmSyncPolicy.evidence.required_verdicts
    )) {
        $property = $verdictRoot.PSObject.Properties[[string]$name]
        if ($null -eq $property -or [string]$property.Value -cne 'PASS') {
            throw "Acceptance evidence is not PASS: $name"
        }
    }
    if ($style -ceq 'flat') {
        if ([string]$Evidence.PROGRAM_RELEASE -cne (
            [string]$script:LlmSyncPolicy.evidence.program_release
        )) {
            throw 'Program release verdict differs.'
        }
        if ([string]$Manifest.acceptance_evidence_sha256 -cne (
            Get-LlmSha256File -Path $EvidencePath
        )) {
            throw 'Acceptance evidence SHA-256 differs.'
        }
        if ($null -eq $Evidence.release_binding) {
            throw 'Acceptance evidence release binding is missing.'
        }
        foreach ($field in @(
            'target',
            'version',
            'tag',
            'asset',
            'package_manifest_sha256',
            'components_lock_sha256',
            'source',
            'foundation_engine_version',
            'foundation_engine_manifest_sha256'
        )) {
            $left = $Evidence.release_binding.$field |
                ConvertTo-Json -Compress -Depth 30
            $right = $Manifest.$field |
                ConvertTo-Json -Compress -Depth 30
            if ($left -cne $right) {
                throw "Acceptance evidence binding differs: $field"
            }
        }
    }
    else {
        if ([string]$Evidence.asset_sha256 -cne (
            [string]$Manifest.asset.sha256
        ) -or
            [string]$Evidence.release_manifest_sha256 -cne (
                Get-LlmSha256File -Path $ManifestPath
            )) {
            throw 'Acceptance evidence file binding differs.'
        }
    }
}

function Assert-LlmReleaseFiles {
    param(
        [Parameter(Mandatory = $true)][string]$Directory,
        [Parameter(Mandatory = $true)][string]$Tag
    )

    $prefix = [regex]::Escape([string]$script:LlmSyncPolicy.tag_prefix)
    $match = [regex]::Match(
        $Tag,
        '^' + $prefix + '(\d+\.\d+\.\d+)$'
    )
    if (-not $match.Success) {
        throw 'Release tag is invalid.'
    }
    $version = $match.Groups[1].Value
    $assetName = (
        [string]$script:LlmSyncPolicy.target +
        '-base-' + $version + '.zip'
    )
    $assetPath = Join-Path $Directory $assetName
    $manifestPath = Join-Path $Directory 'release-manifest.json'
    $lockPath = Join-Path $Directory 'components.lock.json'
    $evidencePath = Join-Path $Directory 'acceptance-evidence.json'
    foreach ($path in @(
        $assetPath,
        $manifestPath,
        $lockPath,
        $evidencePath
    )) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Release asset is missing: $(Split-Path -Leaf $path)"
        }
    }
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
        $lock = Get-Content -LiteralPath $lockPath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
        $evidence = Get-Content -LiteralPath $evidencePath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw 'Release JSON asset is invalid.'
    }
    if ([int]$manifest.schema_version -ne 1 -or
        [string]$manifest.target -cne [string]$script:LlmSyncPolicy.target -or
        [string]$manifest.version -cne $version -or
        [string]$manifest.tag -cne $Tag -or
        [string]$manifest.channel -cne 'stable' -or
        [string]$manifest.client.id -cne (
            [string]$script:LlmSyncPolicy.client.id
        ) -or
        [string]::IsNullOrWhiteSpace(
            [string]$manifest.client.supported_version
        ) -or
        [bool]$manifest.requires.immutable_release -ne $true -or
        [bool]$manifest.requires.release_attestation -ne $true) {
        throw 'Stable release manifest contract differs.'
    }
    if ([string]$manifest.asset.name -cne $assetName -or
        [string]$manifest.asset.sha256 -cne (
            Get-LlmSha256File -Path $assetPath
        ) -or
        [long]$manifest.asset.bytes -ne (
            Get-Item -LiteralPath $assetPath
        ).Length) {
        throw 'Release ZIP binding differs.'
    }
    if ([string]$manifest.components_lock_sha256 -cne (
        Get-LlmSha256File -Path $lockPath
    ) -or
        [string]$lock.target -cne [string]$script:LlmSyncPolicy.target -or
        [string]$lock.version -cne $version -or
        [string]$manifest.source.transformation -cne (
            [string]$script:LlmSyncPolicy.transformation
        ) -or
        [string]$manifest.source.commit -notmatch '^[a-f0-9]{40}$' -or
        [string]$manifest.source.tree -notmatch '^[a-f0-9]{40}$') {
        throw 'Release provenance or component lock differs.'
    }
    Assert-LlmReleaseEvidence `
        -Evidence $evidence `
        -Manifest $manifest `
        -EvidencePath $evidencePath `
        -ManifestPath $manifestPath

    Add-Type -AssemblyName System.IO.Compression -ErrorAction Stop
    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop
    $archive = [IO.Compression.ZipFile]::OpenRead($assetPath)
    try {
        foreach ($entry in $archive.Entries) {
            $name = [string]$entry.FullName
            if ($name.StartsWith('/') -or $name.Contains('\') -or
                @($name.Split('/')) -contains '..') {
                throw 'Release ZIP contains an unsafe path.'
            }
        }
        $packageBytes = Read-LlmZipEntryBytes `
            -Archive $archive `
            -Name 'package-manifest.json'
        if ((Get-LlmSha256Bytes -Bytes $packageBytes) -cne (
            [string]$manifest.package_manifest_sha256
        )) {
            throw 'Package manifest SHA-256 differs.'
        }
        $package = [Text.Encoding]::UTF8.GetString($packageBytes) |
            ConvertFrom-Json -ErrorAction Stop
        if ([string]$package.target -cne (
            [string]$script:LlmSyncPolicy.target
        ) -or
            [string]$package.version -cne $version -or
            [string]$package.client.id -cne (
                [string]$manifest.client.id
            ) -or
            [string]$package.client.supported_version -cne (
                [string]$manifest.client.supported_version
            )) {
            throw 'Package target, version, or client differs.'
        }
        $installRoot = [string]$script:LlmSyncPolicy.install_root
        $embeddedLockName = $installRoot + '/base/components.lock.json'
        $embeddedLock = Read-LlmZipEntryBytes `
            -Archive $archive `
            -Name $embeddedLockName
        $externalLock = [IO.File]::ReadAllBytes($lockPath)
        if ((Get-LlmSha256Bytes $embeddedLock) -cne (
            Get-LlmSha256Bytes $externalLock
        )) {
            throw 'Embedded component lock differs.'
        }
        $foundationVersion = [string]$manifest.foundation_engine_version
        if ($foundationVersion -notmatch '^\d+\.\d+\.\d+$' -or
            [string]$package.foundation_engine_version -cne (
                $foundationVersion
            )) {
            throw 'Foundation version binding differs.'
        }
        $foundationPrefix = (
            $installRoot + '/base/foundation/' +
            $foundationVersion + '/'
        )
        $foundationPayloads = [ordered]@{}
        foreach ($name in @(
            'VERSION',
            'foundation.ps1',
            'engine-manifest.json'
        )) {
            $entryName = $foundationPrefix + $name
            $bytes = Read-LlmZipEntryBytes `
                -Archive $archive `
                -Name $entryName
            $row = @($package.files | Where-Object {
                [string]$_.path -ceq $entryName
            })
            if ($row.Count -ne 1 -or
                [string]$row[0].sha256 -cne (
                    Get-LlmSha256Bytes $bytes
                ) -or
                [long]$row[0].bytes -ne $bytes.Length) {
                throw "Foundation package row differs: $name"
            }
            $foundationPayloads[$name] = $bytes
        }
        $engineManifestBytes = $foundationPayloads['engine-manifest.json']
        if ((Get-LlmSha256Bytes $engineManifestBytes) -cne (
            [string]$manifest.foundation_engine_manifest_sha256
        )) {
            throw 'Foundation engine manifest SHA-256 differs.'
        }
        $engineManifest = [Text.Encoding]::UTF8.GetString(
            $engineManifestBytes
        ) | ConvertFrom-Json -ErrorAction Stop
        if ([int]$engineManifest.schema_version -ne 1 -or
            [int]$engineManifest.protocol_version -ne 1 -or
            [string]$engineManifest.engine_version -cne $foundationVersion -or
            [string]$engineManifest.network -cne 'offline' -or
            (@($engineManifest.commands) -join ',') -cne (
                'doctor,install,inventory,plan,rollback'
            ) -or
            (@($engineManifest.supported_powershell) -join ',') -cne (
                '5.1,7'
            ) -or
            [string]$engineManifest.foundation_ps1_sha256 -cne (
                Get-LlmSha256Bytes $foundationPayloads['foundation.ps1']
            ) -or
            [Text.Encoding]::UTF8.GetString(
                $foundationPayloads['VERSION']
            ).Trim() -cne $foundationVersion) {
            throw 'Foundation engine contract differs.'
        }
    }
    finally {
        $archive.Dispose()
    }

    $foundationRoot = Join-Path $Directory 'verified-foundation'
    [IO.Directory]::CreateDirectory($foundationRoot) | Out-Null
    foreach ($name in $foundationPayloads.Keys) {
        [IO.File]::WriteAllBytes(
            (Join-Path $foundationRoot $name),
            $foundationPayloads[$name]
        )
    }
    return [pscustomobject][ordered]@{
        asset_path = $assetPath
        foundation_path = Join-Path $foundationRoot 'foundation.ps1'
        client_id = [string]$manifest.client.id
        client_version = [string]$manifest.client.supported_version
    }
}

function Get-LlmClientVersion {
    $command = @($script:LlmSyncPolicy.client.command)
    $executable = Get-Command $command[0] -ErrorAction SilentlyContinue
    if ($null -eq $executable) {
        throw "Client is missing: $($command[0])"
    }
    $arguments = @()
    if ($command.Count -gt 1) {
        $arguments = @($command[1..($command.Count - 1)])
    }
    $output = & $executable.Source @arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw 'Client version check failed.'
    }
    $match = [regex]::Match(
        ($output -join "`n").Trim(),
        [string]$script:LlmSyncPolicy.client.version_pattern
    )
    if (-not $match.Success -or
        [string]::IsNullOrWhiteSpace($match.Groups['version'].Value)) {
        throw 'Client version could not be verified.'
    }
    return $match.Groups['version'].Value
}

function Invoke-LlmFoundationCommand {
    param(
        [Parameter(Mandatory = $true)]$Verified,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string]$ClientVersion
    )

    $powershell = Get-Command powershell.exe -ErrorAction SilentlyContinue
    if ($null -eq $powershell) {
        throw 'Windows PowerShell is required.'
    }
    $arguments = @(
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        [string]$Verified.foundation_path,
        $Command,
        '-TargetHome',
        [IO.Path]::GetFullPath($TargetHome),
        '-Target',
        [string]$script:LlmSyncPolicy.target,
        '-Json'
    )
    if ($Command -in @('plan', 'install')) {
        $arguments += @('-Package', [string]$Verified.asset_path)
    }
    if ($Command -in @('plan', 'install', 'doctor')) {
        $arguments += @(
            '-ClientId',
            [string]$Verified.client_id,
            '-ClientVersion',
            $ClientVersion
        )
    }
    $output = & $powershell.Source @arguments 2>&1
    return [pscustomobject][ordered]@{
        exit_code = $LASTEXITCODE
        output = ($output -join "`n")
    }
}

function Invoke-LlmSyncMain {
    if ([string]$script:LlmSyncPolicy.client.acceptance -cne 'PASS') {
        throw 'Client release contract is not accepted; canary is required.'
    }
    if (-not (Test-Path -LiteralPath $TargetHome -PathType Container)) {
        throw 'Target home does not exist.'
    }
    if ($null -eq (Get-Command gh -ErrorAction SilentlyContinue)) {
        throw 'GitHub CLI (gh) is required.'
    }
    $connectionPath = Join-Path (
        [IO.Path]::GetFullPath($TargetHome)
    ) (
        ([string]$script:LlmSyncPolicy.install_root).Replace('/', '\') +
        '\base\runtime\connection.ps1'
    )
    if (-not (Test-Path -LiteralPath $connectionPath -PathType Leaf)) {
        throw 'Installed connection runtime is missing.'
    }
    . $connectionPath

    $tag = Invoke-WithLlmConnection `
        -HomePath $TargetHome `
        -ScriptBlock {
            Get-LlmLatestStableTag
        }
    if ($Check) {
        Write-Output $tag
        return 0
    }

    $temporary = Join-Path ([IO.Path]::GetTempPath()) (
        'llm-base-sync-' + [Guid]::NewGuid().ToString('N')
    )
    [IO.Directory]::CreateDirectory($temporary) | Out-Null
    try {
        Invoke-WithLlmConnection `
            -HomePath $TargetHome `
            -ScriptBlock {
                Invoke-LlmGh -Arguments @(
                    'release',
                    'verify',
                    $tag,
                    '-R',
                    [string]$script:LlmSyncPolicy.repository
                ) | Out-Null
                Invoke-LlmGh -Arguments @(
                    'release',
                    'download',
                    $tag,
                    '-R',
                    [string]$script:LlmSyncPolicy.repository,
                    '--dir',
                    $temporary,
                    '--pattern',
                    '*-base-*.zip',
                    '--pattern',
                    'release-manifest.json',
                    '--pattern',
                    'components.lock.json',
                    '--pattern',
                    'acceptance-evidence.json'
                ) | Out-Null
                foreach ($path in @(
                    Get-ChildItem -LiteralPath $temporary -File |
                        Sort-Object Name
                )) {
                    Invoke-LlmGh -Arguments @(
                        'release',
                        'verify-asset',
                        $tag,
                        $path.FullName,
                        '-R',
                        [string]$script:LlmSyncPolicy.repository
                    ) | Out-Null
                    Invoke-LlmGh -Arguments @(
                        'attestation',
                        'verify',
                        $path.FullName,
                        '--repo',
                        [string]$script:LlmSyncPolicy.repository
                    ) | Out-Null
                }
            }
        $verified = Assert-LlmReleaseFiles `
            -Directory $temporary `
            -Tag $tag
        $clientVersion = Get-LlmClientVersion
        if ($clientVersion -cne [string]$verified.client_version) {
            throw 'Installed client version is not accepted by this release.'
        }
        $installed = $false
        foreach ($command in @('plan', 'install', 'doctor')) {
            $result = Invoke-LlmFoundationCommand `
                -Verified $verified `
                -Command $command `
                -ClientVersion $clientVersion
            if ([int]$result.exit_code -ne 0) {
                if ($installed) {
                    $rollback = Invoke-LlmFoundationCommand `
                        -Verified $verified `
                        -Command 'rollback' `
                        -ClientVersion $clientVersion
                    if ([int]$rollback.exit_code -ne 0) {
                        throw (
                            "Foundation $command failed and rollback failed."
                        )
                    }
                }
                throw "Foundation $command failed."
            }
            if ($command -ceq 'install') {
                $installed = $true
            }
            if (-not [string]::IsNullOrWhiteSpace(
                [string]$result.output
            )) {
                Write-Output $result.output
            }
        }
        Write-Output (
            [string]$script:LlmSyncPolicy.target +
            '-base ' + $tag + ' installed and verified.'
        )
        return 0
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Container) {
            Remove-Item -LiteralPath $temporary -Recurse -Force
        }
    }
}

if ($LibraryMode) {
    $script:LlmSyncPolicy = Get-LlmSyncPolicy -Path $PolicyPath
    return
}

try {
    $script:LlmSyncPolicy = Get-LlmSyncPolicy -Path $PolicyPath
    exit (Invoke-LlmSyncMain)
}
catch {
    [Console]::Error.WriteLine('BLOCKED: ' + $_.Exception.Message)
    exit 2
}
