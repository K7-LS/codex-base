$ErrorActionPreference = 'Stop'
$Utf8NoBom = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$runtimeRoot = Split-Path -Parent $PSScriptRoot
$baseHome = $env:CODEX_BASE_HOME_OVERRIDE
if ([string]::IsNullOrWhiteSpace($baseHome)) {
    $baseHome = Split-Path -Parent $runtimeRoot
}
$script:SystemMessages = New-Object 'Collections.Generic.List[string]'

function Complete-Hook {
    if ($script:SystemMessages.Count -gt 0) {
        [ordered]@{
            systemMessage = (@($script:SystemMessages) -join "`n")
        } | ConvertTo-Json -Compress
    }
    exit 0
}

try {
    $updaterPath = Join-Path $runtimeRoot 'update-session-tools.ps1'
    $powershellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if ((Test-Path -LiteralPath $updaterPath -PathType Leaf) -and
        (Test-Path -LiteralPath $powershellPath -PathType Leaf)) {
        $updaterOutput = @(& $powershellPath -NoLogo -NoProfile -NonInteractive `
            -ExecutionPolicy Bypass -File $updaterPath -HookFallback 2>$null)
        if ($updaterOutput -ccontains 'TOOLS_APPLIED_NEXT_SESSION') {
            $script:SystemMessages.Add('TOOLS_APPLIED_NEXT_SESSION')
        }
    }
} catch { }

$connectionRuntime = Join-Path $runtimeRoot 'connection.ps1'
if (-not (Test-Path -LiteralPath $connectionRuntime -PathType Leaf)) { Complete-Hook }
. $connectionRuntime

function Write-Utf8NoBom {
    param([string]$Path, [string]$Text)
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $encoding)
}

try {
    $versionPath = Join-Path $baseHome 'VERSION'
    if (-not (Test-Path -LiteralPath $versionPath -PathType Leaf)) { Complete-Hook }

    $stateRoot = Join-Path $baseHome 'state'
    $statePath = Join-Path $stateRoot 'update-check.json'
    $now = [DateTimeOffset]::UtcNow
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        try {
            $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 |
                ConvertFrom-Json
            $checked = [DateTimeOffset]::Parse([string]$state.checked_at)
            if (($now - $checked).TotalHours -lt 24) { Complete-Hook }
        } catch {
            # Corrupt local TTL state is replaced by a fresh read-only check.
        }
    }

    $fixture = $env:CODEX_BASE_RELEASE_FIXTURE
    if (-not [string]::IsNullOrWhiteSpace($fixture)) {
        $releases = Get-Content -LiteralPath $fixture -Raw -Encoding UTF8 |
            ConvertFrom-Json
    } else {
        $releases = Invoke-WithLlmConnection `
            -HomePath $env:USERPROFILE `
            -ScriptBlock {
                Invoke-LlmJsonGet `
                    -Uri 'https://api.github.com/repos/K7-LS/codex-base/releases?per_page=20' `
                    -UserAgent 'codex-base-version-check/1' `
                    -TimeoutSeconds 5
            }
    }

    $stable = @($releases) |
        Where-Object {
            (-not $_.draft) -and
            (-not $_.prerelease) -and
            ([string]$_.tag_name -match '^codex-v\d+\.\d+\.\d+$')
        } |
        Sort-Object -Property published_at -Descending |
        Select-Object -First 1

    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    $statePayload = [ordered]@{
        checked_at = $now.ToString('o')
        latest_tag = if ($stable) { [string]$stable.tag_name } else { $null }
    } | ConvertTo-Json -Compress
    Write-Utf8NoBom -Path $statePath -Text ($statePayload + "`n")

    if (-not $stable) { Complete-Hook }
    $currentText = (Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8).Trim()
    $latestText = ([string]$stable.tag_name) -replace '^codex-v', ''
    try {
        $current = [version]$currentText
        $latest = [version]$latestText
    } catch {
        Complete-Hook
    }
    if ($latest -le $current) { Complete-Hook }

    $script:SystemMessages.Add(
        "Codex-base $latestText is available. Run `$sync-base for a verified update."
    )
} catch {
    # A version check must never block or add failure noise to session startup.
}
Complete-Hook
