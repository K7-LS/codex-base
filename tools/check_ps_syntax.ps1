param(
    [Parameter(Mandatory = $true)]
    [string]$Root
)

$ErrorActionPreference = 'Stop'
$failed = $false
$files = Get-ChildItem -LiteralPath $Root -Recurse -File -Filter '*.ps1'
foreach ($file in $files) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $file.FullName,
        [ref]$tokens,
        [ref]$errors
    )
    if ($errors.Count -gt 0) {
        $failed = $true
        foreach ($errorItem in $errors) {
            [Console]::Error.WriteLine(
                $file.FullName + ':' + $errorItem.Extent.StartLineNumber + ': ' +
                $errorItem.Message
            )
        }
    }
}
if ($failed) { exit 1 }
Write-Output ('PowerShell syntax PASS: ' + $files.Count)
exit 0
