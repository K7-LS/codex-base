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
$scriptPath = Join-Path $env:USERPROFILE ".hindsight/coding-agents/dist/$($scripts[$EventName])"
$settingsPath = Join-Path $env:USERPROFILE '.hindsight/coding-agent.json'
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
    exit 0
}

$payload = [Console]::In.ReadToEnd()
$payload | & node $scriptPath
exit $LASTEXITCODE
