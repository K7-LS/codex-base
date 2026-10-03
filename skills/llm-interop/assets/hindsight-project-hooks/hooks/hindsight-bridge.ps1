param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('SessionStart', 'UserPromptSubmit', 'Stop')]
    [string]$EventName
)

$scripts = @{
    SessionStart = 'codex-sessionstart-hook.js'
    UserPromptSubmit = 'codex-hook.js'
    Stop = 'codex-stop-hook.js'
}
$userHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
if (-not $userHome -or -not (Get-Command node -ErrorAction SilentlyContinue)) { exit 0 }
$scriptPath = Join-Path $userHome ".hindsight/coding-agents/dist/$($scripts[$EventName])"
$settingsPath = Join-Path $userHome '.hindsight/coding-agent.json'
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
    exit 0
}

$payload = [Console]::In.ReadToEnd()
$payload | & node $scriptPath
exit $LASTEXITCODE
