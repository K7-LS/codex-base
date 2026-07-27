Set-StrictMode -Version 2.0
$Utf8NoBom = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$script:LlmConnectionEntropy = [Text.Encoding]::UTF8.GetBytes(
    'llm-foundation-connection-v1'
)
$script:LlmProxyEnvironmentNames = @(
    'HTTP_PROXY',
    'HTTPS_PROXY',
    'ALL_PROXY',
    'NO_PROXY',
    'http_proxy',
    'https_proxy',
    'all_proxy',
    'no_proxy',
    'LLM_FOUNDATION_CONNECTION_MODE'
)

function Get-LlmConnectionProfile {
    [CmdletBinding()]
    param(
        [string]$HomePath = $env:USERPROFILE
    )

    if ([string]::IsNullOrWhiteSpace($HomePath) -or
        -not (Test-Path -LiteralPath $HomePath -PathType Container)) {
        throw 'Connection profile home does not exist.'
    }
    $profilePath = Join-Path $HomePath '.llm-foundation\connection.json'
    if (-not (Test-Path -LiteralPath $profilePath -PathType Leaf)) {
        return [pscustomobject][ordered]@{
            schema_version = 1
            mode = 'Direct'
            proxy = $null
        }
    }
    try {
        $profile = Get-Content -LiteralPath $profilePath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw 'Connection profile is unreadable.'
    }
    $schema = $profile.PSObject.Properties['schema_version']
    $mode = $profile.PSObject.Properties['mode']
    if ($null -eq $schema -or [int]$schema.Value -ne 1 -or
        $null -eq $mode -or
        [string]$mode.Value -notin @('Direct', 'VPN', 'Proxy')) {
        throw 'Connection profile schema or mode is invalid.'
    }
    if ([string]$profile.mode -ne 'Proxy') {
        return [pscustomobject][ordered]@{
            schema_version = 1
            mode = [string]$profile.mode
            proxy = $null
        }
    }
    if ($null -eq $profile.proxy -or $null -eq $profile.proxy.auth) {
        throw 'Proxy connection profile is incomplete.'
    }
    $proxyType = [string]$profile.proxy.type
    $hostValue = [string]$profile.proxy.host
    $portValue = 0
    $authMode = [string]$profile.proxy.auth.mode
    if ($proxyType -notin @('HTTP', 'HTTPS', 'SOCKS5') -or
        [string]::IsNullOrWhiteSpace($hostValue) -or
        $hostValue -notmatch '^[A-Za-z0-9._:%\[\]-]+$' -or
        -not [int]::TryParse(
            [string]$profile.proxy.port,
            [ref]$portValue
        ) -or
        $portValue -lt 1 -or $portValue -gt 65535 -or
        $authMode -notin @('None', 'UsernamePassword')) {
        throw 'Proxy connection profile is invalid.'
    }
    $username = $null
    if ($authMode -eq 'UsernamePassword') {
        $username = [string]$profile.proxy.auth.username
        if ([string]::IsNullOrWhiteSpace($username)) {
            throw 'Proxy username is required.'
        }
    }
    return [pscustomobject][ordered]@{
        schema_version = 1
        mode = 'Proxy'
        proxy = [pscustomobject][ordered]@{
            type = $proxyType
            host = $hostValue
            port = $portValue
            auth = [pscustomobject][ordered]@{
                mode = $authMode
                username = $username
            }
        }
    }
}

function Get-LlmConnectionPlainPassword {
    param(
        [Parameter(Mandatory = $true)][string]$HomePath
    )

    if ($null -eq (
        'Security.Cryptography.ProtectedData' -as [type]
    )) {
        Add-Type -AssemblyName System.Security -ErrorAction Stop
    }
    $credentialPath = Join-Path (
        [IO.Path]::GetFullPath($HomePath)
    ) '.llm-foundation\connection.cred'
    if (-not (Test-Path -LiteralPath $credentialPath -PathType Leaf)) {
        throw (
            'Protected proxy credential is missing. Save the connection ' +
            'profile again in LLM Foundation Installer.'
        )
    }
    $encrypted = $null
    $plain = $null
    $password = $null
    try {
        $encrypted = [Convert]::FromBase64String(
            (Get-Content -LiteralPath $credentialPath -Raw).Trim()
        )
        $plain = [Security.Cryptography.ProtectedData]::Unprotect(
            $encrypted,
            $script:LlmConnectionEntropy,
            [Security.Cryptography.DataProtectionScope]::CurrentUser
        )
        $password = [Text.Encoding]::Unicode.GetString($plain)
        if ([string]::IsNullOrEmpty($password)) {
            throw 'Protected proxy credential is empty.'
        }
        return $password
    }
    catch {
        throw 'Protected proxy credential cannot be decrypted for this user.'
    }
    finally {
        if ($null -ne $plain) {
            [Array]::Clear($plain, 0, $plain.Length)
        }
        if ($null -ne $encrypted) {
            [Array]::Clear($encrypted, 0, $encrypted.Length)
        }
    }
}

function Format-LlmProxyHost {
    param(
        [Parameter(Mandatory = $true)][string]$HostValue
    )

    if ($HostValue.StartsWith('[') -and $HostValue.EndsWith(']')) {
        return $HostValue
    }
    if ($HostValue.Contains(':')) {
        return "[$HostValue]"
    }
    return $HostValue
}

function Set-LlmConnectionEnvironment {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$Profile,
        [string]$HomePath = $env:USERPROFILE
    )

    foreach ($name in $script:LlmProxyEnvironmentNames) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
    $env:LLM_FOUNDATION_CONNECTION_MODE = [string]$Profile.mode
    if ([string]$Profile.mode -ne 'Proxy') {
        $env:NO_PROXY = '*'
        return [pscustomobject][ordered]@{
            mode = [string]$Profile.mode
            uses_proxy = $false
            proxy_type = $null
        }
    }

    $scheme = switch ([string]$Profile.proxy.type) {
        'HTTP' { 'http' }
        'HTTPS' { 'https' }
        'SOCKS5' { 'socks5h' }
        default { throw 'Proxy type is not supported.' }
    }
    $password = $null
    $userInfo = ''
    try {
        if ([string]$Profile.proxy.auth.mode -eq 'UsernamePassword') {
            $password = Get-LlmConnectionPlainPassword -HomePath $HomePath
            $userInfo = (
                [Uri]::EscapeDataString(
                    [string]$Profile.proxy.auth.username
                ) + ':' +
                [Uri]::EscapeDataString($password) + '@'
            )
        }
        $proxyUri = (
            '{0}://{1}{2}:{3}' -f
            $scheme,
            $userInfo,
            (Format-LlmProxyHost -HostValue ([string]$Profile.proxy.host)),
            [int]$Profile.proxy.port
        )
        $env:HTTP_PROXY = $proxyUri
        $env:HTTPS_PROXY = $proxyUri
        if ([string]$Profile.proxy.type -eq 'SOCKS5') {
            $env:ALL_PROXY = $proxyUri
        }
    }
    finally {
        $password = $null
        $userInfo = $null
        $proxyUri = $null
    }
    return [pscustomobject][ordered]@{
        mode = 'Proxy'
        uses_proxy = $true
        proxy_type = [string]$Profile.proxy.type
    }
}

function Invoke-WithLlmConnection {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][scriptblock]$ScriptBlock,
        [string]$HomePath = $env:USERPROFILE
    )

    $previous = @{}
    foreach ($name in $script:LlmProxyEnvironmentNames) {
        $item = Get-Item "Env:$name" -ErrorAction SilentlyContinue
        $previous[$name] = [pscustomobject]@{
            exists = $null -ne $item
            value = if ($null -ne $item) { [string]$item.Value } else { $null }
        }
    }
    try {
        $profile = Get-LlmConnectionProfile -HomePath $HomePath
        Set-LlmConnectionEnvironment `
            -Profile $profile `
            -HomePath $HomePath | Out-Null
        & $ScriptBlock
    }
    finally {
        foreach ($name in $script:LlmProxyEnvironmentNames) {
            if ($previous[$name].exists) {
                Set-Item "Env:$name" $previous[$name].value
            }
            else {
                Remove-Item "Env:$name" -ErrorAction SilentlyContinue
            }
        }
    }
}

function Invoke-LlmJsonGet {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$UserAgent,
        [int]$TimeoutSeconds = 10
    )

    $parsed = $null
    if (-not [Uri]::TryCreate(
        $Uri,
        [UriKind]::Absolute,
        [ref]$parsed
    ) -or
        $parsed.Scheme -notin @('http', 'https') -or
        $TimeoutSeconds -lt 1 -or
        $TimeoutSeconds -gt 60 -or
        [string]::IsNullOrWhiteSpace($UserAgent)) {
        throw 'JSON GET request contract is invalid.'
    }
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($null -eq $curl) {
        throw 'Windows curl.exe is required for the connection check.'
    }
    $output = & $curl.Source @(
        '--fail',
        '--silent',
        '--show-error',
        '--location',
        '--connect-timeout',
        [string][Math]::Min(5, $TimeoutSeconds),
        '--max-time',
        [string]$TimeoutSeconds,
        '--header',
        'Accept: application/vnd.github+json',
        '--user-agent',
        $UserAgent,
        '--url',
        $Uri
    ) 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw 'JSON GET request failed.'
    }
    try {
        return ($output -join "`n") |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw 'JSON GET response is invalid.'
    }
}
