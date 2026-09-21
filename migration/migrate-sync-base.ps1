[CmdletBinding()]
param(
    [string]$WorkDirectory = '',
    [string]$TargetHome = $env:USERPROFILE,
    [ValidateSet('Verify', 'Plan', 'Install')][string]$Mode = 'Verify',
    [switch]$LibraryMode
)

# Explicit, one-time protocol migration. Verify the migration release and its
# assets BEFORE executing this script; see the included README.md.
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:MigrationRepository = 'K7-LS/codex-base'
$script:MigrationTag = 'codex-v0.2.2'
$script:MigrationVersion = '0.2.2'
$script:MigrationClient = '0.153.1'
$script:MigrationRuntime = Join-Path $PSScriptRoot 'connection.ps1'
$script:MigrationRuntimeSha256 = '3fc62daf9d8d8efb550424c53de4308e3cbc1e056aa9be6d877fd60681a3779c'
# Pins are the exact immutable codex-v0.2.2 assets, not synthetic evidence.
$script:MigrationAssetPins = @'
{
  "acceptance-evidence.json": {"bytes":1255716,"sha256":"491618f289244c871d22bd77533bc3f492c72e25c13a304fd51cda2d1e1a89a7"},
  "codex-base-0.2.2.zip": {"bytes":13284602,"sha256":"d9f67ef2617fdcdd3c3748cad38f9325bd5854f300f67ac1c2d940b0273e9b3b"},
  "components.lock.json": {"bytes":83137,"sha256":"c4d88095f6a9fa9f76db17ba855c7b2776d585cf1dddf2a8ba9783e39cc69a1a"},
  "release-manifest.json": {"bytes":1967,"sha256":"f5110d4598b1a08078b13dccbcf49180ba7a1d296dca6ef3a06e909cb3115b29"},
  "session-tools-codex-0.2.2.zip": {"bytes":7003,"sha256":"472f24abdcb67d1db3eb41535c55040bcec09a49baf3fa758cf2519759e5b9a1"}
}
'@ | ConvertFrom-Json

function Get-MigrationHash {
    param([byte[]]$Bytes)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return -join ($algorithm.ComputeHash($Bytes) | ForEach-Object { $_.ToString('x2') }) }
    finally { $algorithm.Dispose() }
}

function Invoke-MigrationGh {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    # Never retain native stderr: a connection error can contain proxy details.
    $previousPreference = $ErrorActionPreference
    try {
        # In Windows PowerShell, redirected native stderr is an ErrorRecord
        # even when gh succeeds. Capture it, then judge the native exit code.
        $ErrorActionPreference = 'Continue'
        $output = & gh @Arguments 2>&1
        if ($LASTEXITCODE -ne 0) { throw 'native command failed' }
    }
    catch { throw ('GitHub verification failed: gh ' + ($Arguments[0..1] -join ' ')) }
    finally { $ErrorActionPreference = $previousPreference }
    return ($output -join "`n")
}

function Get-MigrationPhysicalPath {
    param([string]$Path)
    if ($Path.StartsWith('\\?\') -or $Path.StartsWith('\\.\')) {
        throw 'Device and extended path namespaces are not supported for migration staging or home.'
    }
    # Check the original spelling: .NET/Win32 can trim a trailing dot before
    # GetFullPath returns, hiding the ambiguity from later leaf checks.
    foreach ($segment in ($Path -split '[\\/]')) {
        if ($segment -notin @('', '.', '..') -and $segment -match '[. ]$') {
            throw 'Migration path has an ambiguous Windows segment.'
        }
    }
    if ($null -eq ('K7MigrationPhysicalPath' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
public static class K7MigrationPhysicalPath {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern SafeFileHandle CreateFile(string path, uint access, uint share,
        IntPtr security, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern uint GetFinalPathNameByHandle(SafeFileHandle handle,
        StringBuilder path, uint length, uint flags);
    public static string Resolve(string path) {
        using (var handle = CreateFile(path, 0, 7, IntPtr.Zero, 3, 0x02000000, IntPtr.Zero)) {
            if (handle.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
            var result = new StringBuilder(32768);
            uint length = GetFinalPathNameByHandle(handle, result, (uint)result.Capacity, 0);
            if (length == 0 || length >= result.Capacity)
                throw new Win32Exception(Marshal.GetLastWin32Error());
            return result.ToString();
        }
    }
}
'@
    }
    $cursor = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $suffix = New-Object 'Collections.Generic.List[string]'
    while (-not (Test-Path -LiteralPath $cursor)) {
        $leaf = Split-Path -Leaf $cursor
        if ([string]::IsNullOrWhiteSpace($leaf) -or $leaf -match '[. ]$') {
            throw 'Migration path has an ambiguous Windows segment.'
        }
        $suffix.Insert(0, $leaf)
        $cursor = Split-Path -Parent $cursor
        if ([string]::IsNullOrWhiteSpace($cursor)) { throw 'Migration path has no existing parent.' }
    }
    if (-not (Test-Path -LiteralPath $cursor -PathType Container)) { throw 'Migration path parent is not a directory.' }
    $resolved = [K7MigrationPhysicalPath]::Resolve($cursor)
    if ($resolved.StartsWith('\\?\UNC\')) { $resolved = '\\' + $resolved.Substring(8) }
    elseif ($resolved.StartsWith('\\?\')) { $resolved = $resolved.Substring(4) }
    foreach ($leaf in $suffix) { $resolved = Join-Path $resolved $leaf }
    return $resolved.TrimEnd('\', '/')
}

function Assert-MigrationLatestRelease {
    $json = Invoke-MigrationGh -Arguments @('release', 'list', '-R', $script:MigrationRepository,
        '--limit', '100', '--json', 'tagName,isDraft,isPrerelease,isImmutable')
    try { $releases = $json | ConvertFrom-Json }
    catch { throw 'GitHub release discovery returned invalid JSON.' }
    # PS5.1 emits the JSON array as one pipeline object. Enumerate the parsed
    # collection explicitly before filtering/sorting individual releases.
    $candidates = @()
    foreach ($release in $releases) {
        if ($release.tagName -cmatch '^codex-v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' -and
            $release.isDraft -eq $false -and $release.isPrerelease -eq $false) {
            $candidates += $release
        }
    }
    $candidates = @($candidates | Sort-Object { [version]($_.tagName.Substring(7)) } -Descending)
    if ($candidates.Count -eq 0 -or $candidates[0].tagName -cne $script:MigrationTag -or
        $candidates[0].isImmutable -ne $true) {
        throw 'Pinned migration target is not the latest immutable stable; obtain a reviewed hub migration.'
    }
}

function Read-MigrationZipEntry {
    param($Archive, [string]$Name)
    $entries = @($Archive.Entries | Where-Object { $_.FullName -ceq $Name })
    if ($entries.Count -ne 1) { throw "Migration ZIP entry missing or duplicated: $Name" }
    $stream = $entries[0].Open()
    $memory = New-Object IO.MemoryStream
    try { $stream.CopyTo($memory); return ,$memory.ToArray() }
    finally { $memory.Dispose(); $stream.Dispose() }
}

function Export-MigrationUpdater {
    param([string]$AssetDirectory, [string]$Destination)
    $manifest = Get-Content -LiteralPath (Join-Path $AssetDirectory 'release-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.target -cne 'codex' -or $manifest.version -cne $script:MigrationVersion -or
        $manifest.tag -cne $script:MigrationTag -or $manifest.channel -cne 'stable') {
        throw 'Migration release manifest target/version/channel differs.'
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead((Join-Path $AssetDirectory ('codex-base-' + $script:MigrationVersion + '.zip')))
    $payloads = [ordered]@{}
    try {
        $packageBytes = Read-MigrationZipEntry -Archive $archive -Name 'package-manifest.json'
        if ((Get-MigrationHash $packageBytes) -cne $manifest.package_manifest_sha256) {
            throw 'Migration package manifest SHA-256 differs.'
        }
        $package = [Text.Encoding]::UTF8.GetString($packageBytes) | ConvertFrom-Json
        if ($package.target -cne 'codex' -or $package.version -cne $script:MigrationVersion) {
            throw 'Migration package target/version differs.'
        }
        # Only these two fixed paths are extracted. Never use archive-supplied
        # paths as destinations, or mix the new policy with the old script.
        foreach ($relative in @('tools/sync_base.ps1', 'sync-policy.json')) {
            $entryName = '.agents/skills/sync-base/' + $relative
            $rows = @($package.files | Where-Object { $_.path -ceq $entryName })
            if ($rows.Count -ne 1) { throw "Migration updater inventory differs: $relative" }
            $data = Read-MigrationZipEntry -Archive $archive -Name $entryName
            if ((Get-MigrationHash $data) -cne $rows[0].sha256 -or $data.Length -ne $rows[0].bytes) {
                throw "Migration updater SHA-256 differs: $relative"
            }
            $payloads[$relative] = $data
        }
    }
    finally { $archive.Dispose() }
    foreach ($relative in $payloads.Keys) {
        $path = Join-Path $Destination $relative
        [IO.Directory]::CreateDirectory((Split-Path -Parent $path)) | Out-Null
        [IO.File]::WriteAllBytes($path, $payloads[$relative])
    }
}

function Assert-MigrationUniqueJsonKeys {
    param([string]$Json)
    # ConvertFrom-Json silently accepts duplicate keys in both supported shells.
    # Tokenize strings atomically so braces/colons inside values are not syntax.
    $objects = New-Object Collections.Stack
    $tokens = [regex]::Matches($Json, '(?<key>"(?:[^"\\]|\\.)*")\s*:|"(?:[^"\\]|\\.)*"|[{}]')
    foreach ($token in $tokens) {
        if ($token.Value -ceq '{') {
            $objects.Push([Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase))
        }
        elseif ($token.Value -ceq '}') { $null = $objects.Pop() }
        elseif ($token.Groups['key'].Success) {
            $key = ('{"key":' + $token.Groups['key'].Value + '}') | ConvertFrom-Json
            if (-not $objects.Peek().Add([string]$key.key)) { throw 'Duplicate key in Foundation migration plan.' }
        }
    }
}

function Convert-MigrationPlanOutput {
    param([string]$Output, $Verified, [string]$ExpectedHome)
    # The pinned engine emits one compressed JSON line. In PS5.1 Read-Host
    # can echo KEEP/REMOVE into native stdout before that line. Never persist
    # those echoes as JSON, discard arbitrary noise, or choose between plans.
    $planLine = $null
    foreach ($rawLine in ($Output -split '\r?\n')) {
        $line = $rawLine.Trim()
        if (-not $line) { continue }
        if ($null -ne $planLine) { throw 'Ambiguous output after the Foundation migration plan.' }
        if ($line -imatch '^(KEEP|REMOVE)$') { continue }
        if (-not ($line.StartsWith('{') -and $line.EndsWith('}'))) {
            throw 'Unexpected output before the Foundation migration plan.'
        }
        $planLine = $rawLine
    }
    if ($null -eq $planLine) { throw 'Foundation migration plan JSON is missing.' }
    try { $plan = $planLine | ConvertFrom-Json }
    catch { throw 'Foundation migration plan JSON is invalid.' }
    Assert-MigrationUniqueJsonKeys -Json $planLine
    if ($plan -isnot [pscustomobject] -or $plan.client -isnot [pscustomobject]) {
        throw 'Foundation migration plan object type differs.'
    }
    foreach ($name in @('status', 'target', 'release_version', 'package_sha256', 'package_path', 'target_home')) {
        if ($plan.$name -isnot [string]) { throw 'Foundation migration plan binding must be a string.' }
    }
    if ($plan.client.id -isnot [string] -or $plan.client.supported_version -isnot [string]) {
        throw 'Foundation migration client binding must be a string.'
    }
    $packageName = 'codex-base-' + $script:MigrationVersion + '.zip'
    $expectedHash = $script:MigrationAssetPins.PSObject.Properties[$packageName].Value.sha256
    if ((Get-MigrationHash ([IO.File]::ReadAllBytes($Verified.asset_path))) -cne $expectedHash) {
        throw 'Verified migration package changed before apply.'
    }
    if ($plan.status -cne 'READY' -or $plan.target -cne 'codex' -or
        $plan.release_version -cne $script:MigrationVersion -or
        $plan.client.id -cne 'codex-cli' -or $plan.client.supported_version -cne $script:MigrationClient -or
        $plan.package_sha256 -cne $expectedHash -or
        [IO.Path]::GetFullPath($plan.package_path) -ine [IO.Path]::GetFullPath($Verified.asset_path) -or
        (Get-MigrationPhysicalPath $plan.target_home) -ine (Get-MigrationPhysicalPath $ExpectedHome)) {
        throw 'Foundation migration plan binding differs.'
    }
    return $planLine
}

function Invoke-SyncMigration {
    param(
        [Parameter(Mandatory = $true)][string]$WorkDirectory,
        [Parameter(Mandatory = $true)][string]$TargetHome,
        [ValidateSet('Verify', 'Plan', 'Install')][string]$Mode = 'Verify'
    )
    if ($null -eq (Get-Command gh -ErrorAction SilentlyContinue)) { throw 'Required command is missing: gh' }
    if ($null -eq (Get-Command powershell.exe -ErrorAction SilentlyContinue)) { throw 'Required command is missing: powershell.exe' }
    if (-not (Test-Path -LiteralPath $TargetHome -PathType Container)) { throw 'Target home does not exist.' }
    $targetRoot = Get-MigrationPhysicalPath $TargetHome
    $workRoot = Get-MigrationPhysicalPath $WorkDirectory
    if (Test-Path -LiteralPath $workRoot) { throw 'Work directory already exists; use a new empty staging location.' }
    foreach ($relative in @('', '.codex', '.agents', '.llm-foundation')) {
        $protected = if ($relative) { Get-MigrationPhysicalPath (Join-Path $targetRoot $relative) } else { $targetRoot }
        if ($workRoot -ieq $protected -or ($relative -and $workRoot.StartsWith($protected + '\', [StringComparison]::OrdinalIgnoreCase))) {
            throw 'Staging must be outside the managed profile directories.'
        }
    }
    if (-not (Test-Path -LiteralPath $script:MigrationRuntime -PathType Leaf) -or
        (Get-MigrationHash ([IO.File]::ReadAllBytes($script:MigrationRuntime))) -cne $script:MigrationRuntimeSha256) {
        throw 'Pinned migration connection runtime is missing or differs.'
    }
    . $script:MigrationRuntime
    $assetRoot = Join-Path $workRoot 'assets'
    [IO.Directory]::CreateDirectory($assetRoot) | Out-Null
    Invoke-WithLlmConnection -HomePath $targetRoot -ScriptBlock {
        Assert-MigrationLatestRelease
        Invoke-MigrationGh -Arguments @('release', 'verify', $script:MigrationTag, '-R', $script:MigrationRepository) | Out-Null
        Invoke-MigrationGh -Arguments @('release', 'download', $script:MigrationTag, '-R', $script:MigrationRepository, '--dir', $assetRoot) | Out-Null
        $expected = @($script:MigrationAssetPins.PSObject.Properties.Name | Sort-Object)
        $actual = @(Get-ChildItem -LiteralPath $assetRoot -Force | Sort-Object Name)
        if (($actual.Name -join '|') -cne ($expected -join '|') -or @($actual | Where-Object { $_.PSIsContainer }).Count -ne 0) {
            throw 'Downloaded migration target asset set differs.'
        }
        # Serialize gh verification: its Sigstore cache is shared per user.
        foreach ($name in $expected) {
            $path = Join-Path $assetRoot $name
            Invoke-MigrationGh -Arguments @('release', 'verify-asset', $script:MigrationTag, $path, '-R', $script:MigrationRepository) | Out-Null
            Invoke-MigrationGh -Arguments @('attestation', 'verify', $path, '--repo', $script:MigrationRepository) | Out-Null
            $pin = $script:MigrationAssetPins.PSObject.Properties[$name].Value
            $data = [IO.File]::ReadAllBytes($path)
            if ($data.Length -ne $pin.bytes -or (Get-MigrationHash $data) -cne $pin.sha256) {
                throw "Pinned migration target asset differs: $name"
            }
        }
    }
    $updaterRoot = Join-Path $workRoot 'updater'
    Export-MigrationUpdater -AssetDirectory $assetRoot -Destination $updaterRoot
    . (Join-Path $updaterRoot 'tools/sync_base.ps1') -LibraryMode -TargetHome $targetRoot -PolicyPath (Join-Path $updaterRoot 'sync-policy.json')
    $verified = Assert-LlmReleaseFiles -Directory $assetRoot -Tag $script:MigrationTag
    # Keep the pinned workflow/engine unchanged. Adapt only the machine-readable
    # return of its interactive plan command, whose stdout may echo decisions.
    $script:MigrationFoundationCommand = ${function:Invoke-LlmFoundationCommand}
    function Invoke-LlmFoundationCommand {
        param($Verified, [string]$Command, [string]$ClientVersion, [string]$PlanFile)
        $result = & $script:MigrationFoundationCommand @PSBoundParameters
        if ($Command -ceq 'plan' -and $result.exit_code -eq 0) {
            $result.output = Convert-MigrationPlanOutput -Output $result.output -Verified $Verified -ExpectedHome $TargetHome
        }
        return $result
    }
    # Workflow alone does not guard downgrades; SyncMain normally does that.
    $installed = Get-LlmInstalledReleaseVersion
    if ($installed -and [version]$installed -gt [version]$script:MigrationVersion) {
        throw 'Installed base is newer than the migration target; downgrade is forbidden.'
    }
    if ($Mode -ceq 'Verify') {
        [pscustomobject]@{status='VERIFIED'; installation='NOT_RUN'; target='codex'; tag=$script:MigrationTag;
            acceptance_protocol='professional-core-v1'; installed_version=$installed;
            required_client=$script:MigrationClient; client_compatibility='NOT_CHECKED'} | ConvertTo-Json
        return
    }
    if (-not $installed) { throw 'Installed base state is missing; use the official installer for a fresh installation.' }
    if ([version]$installed -eq [version]$script:MigrationVersion) {
        [pscustomobject]@{status='ALREADY_CURRENT'; installation='NOT_RUN'; tag=$script:MigrationTag} | ConvertTo-Json
        return
    }
    $clientVersion = Get-LlmClientVersion
    if ($clientVersion -cne $script:MigrationClient) { throw 'Client compatibility is unaccepted: this migration requires codex-cli 0.153.1. Obtain a reviewed migration for the actual client; do not change client versions automatically.' }
    if ($Mode -ceq 'Plan') {
        $plan = Invoke-LlmFoundationCommand -Verified $verified -Command 'plan' -ClientVersion $clientVersion
        if ($plan.exit_code -ne 0) { throw 'Foundation migration plan failed; installation was not attempted.' }
        [IO.File]::WriteAllText((Join-Path $workRoot 'plan.json'), $plan.output, (New-Object Text.UTF8Encoding($false)))
        Write-Output $plan.output
        return
    }
    $previousTemp = $env:TEMP
    $previousTmp = $env:TMP
    try {
        # Keep the unchanged updater's transient plan in explicit staging.
        $env:TEMP = $workRoot
        $env:TMP = $workRoot
        Invoke-LlmVerifiedWorkflow -Verified $verified -ClientVersion $clientVersion
    }
    finally { $env:TEMP = $previousTemp; $env:TMP = $previousTmp }
}

if ($LibraryMode) { return }
try {
    if ([string]::IsNullOrWhiteSpace($WorkDirectory)) { throw 'Specify -WorkDirectory with a new staging directory.' }
    Invoke-SyncMigration -WorkDirectory $WorkDirectory -TargetHome $TargetHome -Mode $Mode
    exit 0
}
catch { [Console]::Error.WriteLine('BLOCKED: ' + $_.Exception.Message); exit 2 }
