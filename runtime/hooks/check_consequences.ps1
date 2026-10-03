# Managed Codex Base Stop hook: local, deterministic trigger for a second pass.
# It never sends code or transcript content anywhere and does not call a model.
$ErrorActionPreference = 'Stop'

function Complete([object]$Value) {
    $Value | ConvertTo-Json -Compress -Depth 5
    exit 0
}

try {
    $inputText = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($inputText)) { Complete @{} }
    $event = $inputText | ConvertFrom-Json
    if ($event.stop_hook_active -eq $true) { Complete @{} }
    if (-not ($event.cwd -is [string]) -or -not (Test-Path -LiteralPath $event.cwd -PathType Container)) {
        Complete @{}
    }
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if (-not $gitCommand) { Complete @{} }

    $root = & git -C $event.cwd rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $root) { Complete @{} }
    $diff = & git -C $root diff --no-ext-diff --no-color --unified=0 HEAD -- 2>$null
    if ($LASTEXITCODE -ne 0) { Complete @{} }
    $added = @($diff | Where-Object { $_ -match '^\+[^+]' }) -join "`n"
    $paths = @($diff | Where-Object { $_ -match '^\+\+\+ b/' }) -join "`n"
    $untracked = & git -C $root -c core.quotepath=false ls-files --others --exclude-standard 2>$null
    if ($LASTEXITCODE -eq 0) {
        foreach ($relative in @($untracked | Select-Object -First 20)) {
            if ($relative -notmatch '(?i)\.(py|js|jsx|ts|tsx|go|rs|cs|java|ps1|sql)$') { continue }
            $file = Join-Path $root $relative
            if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { continue }
            if ((Get-Item -LiteralPath $file).Length -gt 262144) { continue }
            $paths += "`n$relative"
            $added += "`n" + (Get-Content -LiteralPath $file -Raw -Encoding UTF8)
        }
    }
    if (-not $added) { Complete @{} }

    $payment = ($paths + "`n" + $added) -match '(?i)payment|charge|billing|checkout|refund|invoice'
    $retry = $added -match '(?i)retry|retries|reattempt|replay'
    $access = ($paths + "`n" + $added) -match '(?i)auth|permission|access.control|login'
    $bypass = $added -match '(?i)bypass|disable|skip.check|allow.all'
    $data = ($paths + "`n" + $added) -match '(?i)migration|database|backup|restore|schema'
    $destructive = $added -match '(?i)drop.table|delete.from|truncate|remove-item|rm\s+-rf'
    if (($payment -and $retry) -or ($access -and $bypass) -or ($data -and $destructive)) {
        Complete @{
            decision = 'block'
            reason = 'Codex Base consequence check: inspect the changed behavior and downstream effects before finishing. For a material risk, ask an independent auditor to review the actual diff and tests. In particular, verify idempotency for payment retries, authorization boundaries, or restore/delete safety as applicable. Report the review verdict or the unverified part. Do not infer safety from this keyword trigger alone.'
        }
    }
    Complete @{}
} catch {
    # Advisory check must not prevent work when Git or a host hook schema differs.
    Complete @{}
}
