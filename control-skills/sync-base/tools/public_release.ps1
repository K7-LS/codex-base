# Download immutable GitHub release assets and verify signatures without credentials.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$')][string]$Repository,
    [string]$Stage,
    [string]$Verifier,
    [ValidatePattern('^codex-v\d+\.\d+\.\d+$')][string]$Tag,
    [string]$RepositoryId,
    [string]$OwnerId,
    [switch]$List
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$repo = $Repository
$api = "https://api.github.com/repos/$repo"
$encoding = New-Object Text.UTF8Encoding($false)

function Invoke-CheckedNative {
    param([string]$Command, [string[]]$Arguments)
    $ErrorActionPreference = 'Continue'
    $lines = & $Command @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Verification command failed: $([IO.Path]::GetFileName($Command))" }
    return @($lines | Where-Object { $_ -is [string] })
}

function Get-PublicJson {
    param([string]$Path)
    $lines = Invoke-CheckedNative -Command 'curl.exe' -Arguments @(
        '--disable', '--fail', '--silent', '--show-error', '--proto', '=https',
        '--connect-timeout', '10', '--max-time', '40', '--header', 'Accept: application/vnd.github+json',
        '--user-agent', 'K7-CodexBase', "$api/$Path"
    )
    return ($lines -join "`n") | ConvertFrom-Json
}

function Set-BundleFile {
    param($Attestations, [string]$Destination)
    if (@($Attestations).Count -eq 0) { throw 'Public signature bundle was not found.' }
    $lines = foreach ($attestation in $Attestations) {
        if ([string]$attestation.repository_id -cne $repositoryId -or $null -eq $attestation.bundle) {
            throw 'Public signature bundle repository differs.'
        }
        $attestation.bundle | ConvertTo-Json -Depth 100 -Compress
    }
    [IO.File]::WriteAllLines($Destination, [string[]]@($lines), $encoding)
}

if ($List) {
    $releases = Get-PublicJson 'releases?per_page=100'
    foreach ($row in $releases) {
        [pscustomobject]@{ tagName = $row.tag_name; isDraft = $row.draft; isPrerelease = $row.prerelease }
    }
    return
}
if (-not $Stage -or -not $Tag -or -not $Verifier -or $RepositoryId -cnotmatch '^[0-9]+$' -or
    $OwnerId -cnotmatch '^[0-9]+$') { throw 'Public verification parameters are incomplete.' }
if (Test-Path -LiteralPath $Stage) { throw 'Use a new staging directory.' }
$verifierPath = (Resolve-Path -LiteralPath $Verifier).Path
$work = [IO.Directory]::CreateDirectory([IO.Path]::GetFullPath($Stage)).FullName
$release = Get-PublicJson "releases/tags/$Tag"
if ($release.tag_name -cne $Tag -or $release.immutable -isnot [bool] -or -not $release.immutable -or
    $release.draft -isnot [bool] -or $release.draft -or $release.prerelease -isnot [bool] -or $release.prerelease) {
    throw 'GitHub release is not immutable and stable.'
}
$ref = (Get-PublicJson "git/ref/tags/$Tag").object
for ($i = 0; $i -lt 4 -and $ref.type -ceq 'tag'; $i++) {
    if ([string]$ref.sha -cnotmatch '^[a-f0-9]{40}$') { throw 'Invalid Git tag reference.' }
    $ref = (Get-PublicJson "git/tags/$($ref.sha)").object
}
if ($ref.type -cne 'commit' -or [string]$ref.sha -cnotmatch '^[a-f0-9]{40}$') {
    throw 'Git tag does not resolve to a commit.'
}
$commit = [string]$ref.sha
$purl = "pkg:github/$repo@$Tag"
$releaseBundles = @( (Get-PublicJson "attestations/sha1:$commit`?predicate_type=release&per_page=100").attestations |
    Where-Object { $_.initiator -ceq 'github' } )
$matching = @(foreach ($candidate in $releaseBundles) {
    $statement = [Text.Encoding]::UTF8.GetString(
        [Convert]::FromBase64String($candidate.bundle.dsseEnvelope.payload)) | ConvertFrom-Json
    if ($statement.predicate.tag -ceq $Tag) { $candidate }
})
if ($matching.Count -ne 1) { throw 'GitHub release signature is missing or duplicated.' }
$bundlePath = Join-Path $work 'release-bundle.json'
Set-BundleFile $matching $bundlePath

# Use the existing GH verifier and its own TUF roots in a credential-free child environment.
$saved = @{}
$isolated = @{
    GH_CONFIG_DIR = (Join-Path $work 'gh-config')
    GH_PROMPT_DISABLED = '1'
    XDG_CACHE_HOME = (Join-Path $work 'gh-cache')
    GH_TOKEN = $null
    GITHUB_TOKEN = $null
    GH_ENTERPRISE_TOKEN = $null
    GITHUB_ENTERPRISE_TOKEN = $null
}
try {
    foreach ($name in $isolated.Keys) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $isolated[$name], 'Process')
    }
    $roots = @(Invoke-CheckedNative -Command 'gh' -Arguments @('attestation', 'trusted-root', '--hostname', 'github.com') |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $githubRoots = @(foreach ($line in $roots) {
        $root = $line | ConvertFrom-Json
        $logs = $root.PSObject.Properties['tlogs']
        $timestamps = $root.PSObject.Properties['timestampAuthorities']
        if (($null -eq $logs -or @($logs.Value).Count -eq 0) -and
            $null -ne $timestamps -and @($timestamps.Value).Count -gt 0) { $line }
    })
    if ($githubRoots.Count -ne 1) { throw 'GitHub TUF trusted root is unavailable.' }
    $rootPath = Join-Path $work 'github-root.json'
    [IO.File]::WriteAllText($rootPath, $githubRoots[0], $encoding)
    $verification = Invoke-CheckedNative -Command $verifierPath -Arguments @(
        '--bundle', $bundlePath, '--trusted-root', $rootPath, '--commit', $commit
    )
    $verified = ($verification -join "`n") | ConvertFrom-Json
    $statement = $verified.statement
    $predicate = $statement.predicate
    if ($predicate.repository -cne $repo -or $predicate.tag -cne $Tag -or $predicate.purl -cne $purl -or
        [string]$predicate.repositoryId -cne $repositoryId -or [string]$predicate.ownerId -cne $ownerId -or
        [string]$predicate.databaseId -cne [string]$release.id) {
        throw 'Signed GitHub release identity differs.'
    }
    $version = $Tag.Substring('codex-v'.Length)
    $names = @('acceptance-evidence.json', "codex-base-$version.zip", 'components.lock.json',
        'release-manifest.json', "session-tools-codex-$version.zip")
    $subjects = @($statement.subject)
    $commitSubjects = @($subjects | Where-Object {
        $null -ne $_.PSObject.Properties['uri'] -and $_.uri -ceq $purl -and
        $null -ne $_.digest.PSObject.Properties['sha1'] -and $_.digest.sha1 -ceq $commit
    })
    if ($subjects.Count -ne ($names.Count + 1) -or $commitSubjects.Count -ne 1 -or
        @($release.assets).Count -ne $names.Count) {
        throw 'Signed release asset set differs.'
    }
    foreach ($name in $names) {
        $assets = @($release.assets | Where-Object name -CEQ $name)
        $subject = @($subjects | Where-Object { $null -ne $_.PSObject.Properties['name'] -and $_.name -ceq $name })
        if ($assets.Count -ne 1 -or $subject.Count -ne 1 -or
            [string]$subject[0].digest.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            $assets[0].digest -cne ('sha256:' + $subject[0].digest.sha256)) {
            throw "Signed asset binding differs: $name"
        }
        $destination = Join-Path $work $name
        $url = "https://github.com/$repo/releases/download/$Tag/$name"
        Invoke-CheckedNative -Command 'curl.exe' -Arguments @(
            '--disable', '--fail', '--silent', '--show-error', '--location',
            '--proto', '=https', '--proto-redir', '=https', '--connect-timeout', '10',
            '--max-time', '150', '--output', $destination, $url
        ) | Out-Null
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
        if ($hash -cne $subject[0].digest.sha256 -or (Get-Item -LiteralPath $destination).Length -ne $assets[0].size) {
            throw "Downloaded bytes differ from the signed release: $name"
        }
        $provenance = (Get-PublicJson "attestations/sha256:$hash`?predicate_type=provenance&per_page=100").attestations
        $provenancePath = Join-Path $work "$name.provenance.jsonl"
        Set-BundleFile $provenance $provenancePath
        $signer = "https://github.com/$repo/.github/workflows/attest-release-assets.yml@refs/tags/$Tag"
        $json = Invoke-CheckedNative -Command 'gh' -Arguments @(
            'attestation', 'verify', $destination, '--hostname', 'github.com',
            '--repo', $repo, '--bundle', $provenancePath,
            '--cert-identity', $signer, '--source-digest', $commit, '--deny-self-hosted-runners', '--format', 'json'
        )
        $reports = @(($json -join "`n") | ConvertFrom-Json)
        if (@($reports | Where-Object {
            $certificate = $_.verificationResult.signature.certificate
            [string]$certificate.sourceRepositoryIdentifier -ceq $repositoryId -and
            [string]$certificate.sourceRepositoryOwnerIdentifier -ceq $ownerId
        }).Count -eq 0) {
            throw "Asset signer repository identity differs: $name"
        }
        Write-Output "VERIFIED $name"
    }
    $manifest = Get-Content -LiteralPath (Join-Path $work 'release-manifest.json') -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ($manifest.source.commit -cne $commit -or $manifest.source.repository -cne "https://github.com/$repo") {
        throw 'Manifest source differs from the signed release commit.'
    }
}
finally {
    foreach ($name in $saved.Keys) {
        [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
    }
}
