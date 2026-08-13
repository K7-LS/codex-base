param(
    [switch]$ManagedPreflight,
    [switch]$HookFallback,
    [string]$TransactionId,
    [string]$StartTick,
    [string]$MutationCutoffTick,
    [string]$KillTick,
    [string]$HardDeadlineTick,
    [string]$StopwatchFrequency
)

$ErrorActionPreference = 'Stop'
$script:Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$script:Target = 'codex'
$script:Repository = 'daniileliseev1337/codex-base'
$script:MaxZipBytes = 10MB
$script:MaxExpandedBytes = 8MB
$script:MaxFileBytes = 1MB
$script:AllowedExtensions = @('.json', '.md', '.toml', '.txt', '.yaml', '.yml')

[Console]::OutputEncoding = $script:Utf8NoBom
$OutputEncoding = $script:Utf8NoBom

function Initialize-StrictJsonGuard {
    if (-not ('Foundation.SessionTools.StrictJsonGuard' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;

namespace Foundation.SessionTools
{
    public static class StrictJsonGuard
    {
        public static void Validate(string text)
        {
            if (text == null || (text.Length > 0 && text[0] == '\ufeff'))
                throw new FormatException("invalid UTF-8 JSON");
            Parser parser = new Parser(text);
            parser.Value();
            parser.White();
            if (!parser.End) throw new FormatException("trailing JSON content");
        }

        private sealed class Parser
        {
            private readonly string text;
            private int index;
            internal Parser(string value) { text = value; }
            internal bool End { get { return index == text.Length; } }
            internal void White() { while (index < text.Length && Char.IsWhiteSpace(text[index])) index++; }
            private char Take() { if (index >= text.Length) throw new FormatException("unexpected end"); return text[index++]; }
            private char Peek() { if (index >= text.Length) throw new FormatException("unexpected end"); return text[index]; }
            internal void Value()
            {
                White();
                char value = Peek();
                if (value == '{') Object();
                else if (value == '[') Array();
                else if (value == '"') String(false);
                else if (value == 't') Literal("true");
                else if (value == 'f') Literal("false");
                else if (value == 'n') Literal("null");
                else Number();
            }
            private void Object()
            {
                Take(); White();
                HashSet<string> names = new HashSet<string>(StringComparer.Ordinal);
                if (Peek() == '}') { Take(); return; }
                while (true)
                {
                    string name = String(true);
                    if (!names.Add(name)) throw new FormatException("duplicate JSON key");
                    White(); if (Take() != ':') throw new FormatException("missing colon");
                    Value(); White();
                    char next = Take();
                    if (next == '}') return;
                    if (next != ',') throw new FormatException("invalid object separator");
                    White();
                }
            }
            private void Array()
            {
                Take(); White();
                if (Peek() == ']') { Take(); return; }
                while (true)
                {
                    Value(); White();
                    char next = Take();
                    if (next == ']') return;
                    if (next != ',') throw new FormatException("invalid array separator");
                    White();
                }
            }
            private string String(bool property)
            {
                if (Take() != '"') throw new FormatException("string expected");
                System.Text.StringBuilder result = new System.Text.StringBuilder();
                while (true)
                {
                    char value = Take();
                    if (value == '"') return result.ToString();
                    if (value < 0x20) throw new FormatException("control character");
                    if (value != '\\') { result.Append(value); continue; }
                    if (property) throw new FormatException("escaped property name");
                    char escape = Take();
                    if (escape == 'u')
                    {
                        for (int count = 0; count < 4; count++)
                        {
                            char hex = Take();
                            if (!Uri.IsHexDigit(hex)) throw new FormatException("invalid unicode escape");
                        }
                    }
                    else if ("\"\\/bfnrt".IndexOf(escape) < 0)
                        throw new FormatException("invalid string escape");
                }
            }
            private void Number()
            {
                if (Peek() == '-') Take();
                if (Peek() == '0') Take();
                else { Digit(); while (index < text.Length && Char.IsDigit(text[index])) index++; }
                if (index < text.Length && text[index] == '.')
                { index++; Digit(); while (index < text.Length && Char.IsDigit(text[index])) index++; }
                if (index < text.Length && (text[index] == 'e' || text[index] == 'E'))
                {
                    index++;
                    if (index < text.Length && (text[index] == '+' || text[index] == '-')) index++;
                    Digit(); while (index < text.Length && Char.IsDigit(text[index])) index++;
                }
            }
            private void Digit()
            {
                if (index >= text.Length || !Char.IsDigit(text[index]))
                    throw new FormatException("digit expected");
                index++;
            }
            private void Literal(string value)
            {
                foreach (char expected in value) if (Take() != expected) throw new FormatException("invalid literal");
            }
        }
    }
}
'@
    }
}

function Assert-ExactProperties {
    param($Value, [string[]]$Expected, [string]$Code)
    if ($null -eq $Value -or $Value -isnot [psobject]) { throw $Code }
    $actual = @($Value.PSObject.Properties | ForEach-Object { $_.Name })
    if ($actual.Count -ne $Expected.Count) { throw $Code }
    foreach ($name in $Expected) { if ($actual -cnotcontains $name) { throw $Code } }
}

function Test-ExactInteger {
    param($Value)
    return $Value -is [int] -or $Value -is [long]
}

function ConvertFrom-StrictJsonBytes {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    if ($Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF) {
        throw 'INVALID_JSON'
    }
    $strictUtf8 = New-Object Text.UTF8Encoding($false, $true)
    $text = $strictUtf8.GetString($Bytes)
    Initialize-StrictJsonGuard
    [Foundation.SessionTools.StrictJsonGuard]::Validate($text)
    if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind')) {
        return $text | ConvertFrom-Json -DateKind String -ErrorAction Stop
    }
    return $text | ConvertFrom-Json -ErrorAction Stop
}

function ConvertTo-WindowsArgument {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $builder = New-Object Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes++
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * ($backslashes * 2 + 1)))
            [void]$builder.Append('"')
            $backslashes = 0
            continue
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append(('\' * $backslashes))
            $backslashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) {
        [void]$builder.Append(('\' * ($backslashes * 2)))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function ConvertTo-WindowsCommandLine {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    return (($Arguments | ForEach-Object { ConvertTo-WindowsArgument $_ }) -join ' ')
}

function Get-Sha256Bytes {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $algorithm.Dispose()
    }
}

function Get-Sha256File {
    param([Parameter(Mandatory = $true)][string]$Path)
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}

function Test-ReparseAtOrAbove {
    param([Parameter(Mandatory = $true)][string]$Path)
    $current = [IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return $true }
        }
        $parent = [IO.Path]::GetDirectoryName($current)
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) { break }
        $current = $parent
    }
    return $false
}

function Get-SafeTreeFiles {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (Test-ReparseAtOrAbove $Path) { throw 'UNSAFE_REPARSE_PATH' }
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return }
    $pending = New-Object 'Collections.Generic.Stack[string]'
    $pending.Push([IO.Path]::GetFullPath($Path))
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        foreach ($entry in (Get-ChildItem -LiteralPath $directory -Force)) {
            if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'UNSAFE_REPARSE_PATH'
            }
            if ($entry.PSIsContainer) { $pending.Push($entry.FullName) }
            else { Write-Output $entry.FullName }
        }
    }
}

function Get-Fingerprint {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (Test-ReparseAtOrAbove $Path) { throw 'UNSAFE_REPARSE_PATH' }
    if (Test-Path -LiteralPath $Path -PathType Leaf) { return Get-Sha256File $Path }
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return 'absent' }
    $root = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $rows = New-Object 'Collections.Generic.List[string]'
    foreach ($file in @(Get-SafeTreeFiles $root)) {
        $relative = $file.Substring($root.Length + 1).Replace('\', '/')
        $rows.Add($relative + [char]0 + (Get-Sha256File $file) + "`n")
    }
    $values = $rows.ToArray()
    [Array]::Sort($values, [StringComparer]::Ordinal)
    return Get-Sha256Bytes $script:Utf8NoBom.GetBytes(($values -join ''))
}

function ConvertTo-JsonBytes {
    param([Parameter(Mandatory = $true)]$Value)
    return $script:Utf8NoBom.GetBytes(($Value | ConvertTo-Json -Depth 20) + "`n")
}

function Write-DurableBytes {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][byte[]]$Bytes
    )
    $directory = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    $temporary = Join-Path $directory ('.write-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    $stream = New-Object IO.FileStream(
        $temporary,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None,
        4096,
        [IO.FileOptions]::WriteThrough
    )
    try {
        $stream.Write($Bytes, 0, $Bytes.Length)
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $backup = Join-Path $directory ('.replace-' + [Guid]::NewGuid().ToString('N') + '.bak')
        [IO.File]::Replace($temporary, $Path, $backup, $true)
        [IO.File]::Delete($backup)
    }
    else {
        [IO.File]::Move($temporary, $Path)
    }
}

function Write-DurableJson {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)]$Value)
    Write-DurableBytes -Path $Path -Bytes (ConvertTo-JsonBytes $Value)
}

function Test-LowerSha256 {
    param($Value)
    return $Value -is [string] -and $Value -cmatch '^[0-9a-f]{64}$'
}

function Get-RemainingMilliseconds {
    param([Parameter(Mandatory = $true)][long]$Deadline)
    $remaining = $Deadline - [Diagnostics.Stopwatch]::GetTimestamp()
    if ($remaining -le 0) { return 0 }
    $milliseconds = [Math]::Floor(($remaining * 1000.0) / [Diagnostics.Stopwatch]::Frequency)
    if ($milliseconds -lt 1) { return 1 }
    if ($milliseconds -gt [int]::MaxValue) { return [int]::MaxValue }
    return [int]$milliseconds
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][long]$Deadline
    )
    $milliseconds = Get-RemainingMilliseconds $Deadline
    if ($milliseconds -le 0) { throw 'DEADLINE_REACHED' }
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $FilePath
    $start.Arguments = ConvertTo-WindowsCommandLine $Arguments
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = $script:Utf8NoBom
    $start.StandardErrorEncoding = $script:Utf8NoBom
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        if (-not $process.Start()) { throw 'PROCESS_START_FAILED' }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($milliseconds)) {
            try { $process.Kill() } catch { }
            throw 'DEADLINE_REACHED'
        }
        $stdout = $stdoutTask.Result
        $stderr = $stderrTask.Result
        if ($stdout.Length -gt 1MB -or $stderr.Length -gt 64KB) { throw 'PROCESS_OUTPUT_LIMIT' }
        if ($process.ExitCode -ne 0) { throw 'PROCESS_FAILED' }
        return $stdout
    }
    finally {
        $process.Dispose()
    }
}

function Get-RequiredLong {
    param([Parameter(Mandatory = $true)][string]$Value)
    $number = 0L
    if ($Value -cnotmatch '^[1-9][0-9]*$' -or
        -not [long]::TryParse($Value, [Globalization.NumberStyles]::None, [Globalization.CultureInfo]::InvariantCulture, [ref]$number) -or
        $number -le 0) {
        throw 'INVALID_CLOCK_CONTRACT'
    }
    return $number
}

function Get-ClockContract {
    if ($ManagedPreflight -and $HookFallback) { throw 'INVALID_MODE' }
    if ($ManagedPreflight) {
        if ($TransactionId -cnotmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') {
            throw 'INVALID_TRANSACTION_ID'
        }
        $parsed = [Guid]::Empty
        if (-not [Guid]::TryParseExact($TransactionId, 'D', [ref]$parsed) -or
            $parsed.ToString('D') -cne $TransactionId) {
            throw 'INVALID_TRANSACTION_ID'
        }
        $start = Get-RequiredLong $StartTick
        $mutation = Get-RequiredLong $MutationCutoffTick
        $kill = Get-RequiredLong $KillTick
        $hard = Get-RequiredLong $HardDeadlineTick
        $frequency = Get-RequiredLong $StopwatchFrequency
        if ($frequency -ne [Diagnostics.Stopwatch]::Frequency -or
            $frequency -gt [long]::MaxValue / 30 -or
            $start -gt [long]::MaxValue - (30 * $frequency) -or
            $mutation -ne $start + (22 * $frequency) -or
            $kill -ne $start + (25 * $frequency) -or
            $hard -ne $start + (30 * $frequency)) {
            throw 'INVALID_CLOCK_CONTRACT'
        }
        return [pscustomobject][ordered]@{
            transaction_id = $TransactionId
            start_tick = $start
            mutation_cutoff_tick = $mutation
            kill_tick = $kill
            hard_deadline_tick = $hard
            stopwatch_frequency = $frequency
        }
    }
    if (-not $HookFallback) { throw 'INVALID_MODE' }
    $frequency = [Diagnostics.Stopwatch]::Frequency
    $start = [Diagnostics.Stopwatch]::GetTimestamp()
    return [pscustomobject][ordered]@{
        transaction_id = [Guid]::NewGuid().ToString('D')
        start_tick = $start
        mutation_cutoff_tick = $start + (22 * $frequency)
        kill_tick = $start + (25 * $frequency)
        hard_deadline_tick = $start + (30 * $frequency)
        stopwatch_frequency = $frequency
    }
}

function Read-JsonObject {
    param([Parameter(Mandatory = $true)][string]$Path)
    return ConvertFrom-StrictJsonBytes ([IO.File]::ReadAllBytes($Path))
}

function Get-ReceiptHash {
    param([Parameter(Mandatory = $true)][string]$UserRoot)
    $receiptPath = Join-Path $UserRoot '.llm-foundation\bin\codex-managed.receipt.json'
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf) -or
        (Test-ReparseAtOrAbove $receiptPath)) { throw 'RECEIPT_REQUIRED' }
    $receipt = Read-JsonObject $receiptPath
    Assert-ExactProperties $receipt @(
        'schema_version', 'target', 'launcher_path', 'launcher_sha256',
        'updater_path', 'vendor_executable_path'
    ) 'INVALID_RECEIPT'
    $expectedLauncher = Join-Path $UserRoot '.llm-foundation\bin\codex-managed.exe'
    $launcherPath = [IO.Path]::GetFullPath([string]$receipt.launcher_path)
    if (-not (Test-ExactInteger $receipt.schema_version) -or $receipt.schema_version -ne 1 -or
        [string]$receipt.target -cne $script:Target -or
        -not (Test-LowerSha256 $receipt.launcher_sha256) -or
        -not [StringComparer]::OrdinalIgnoreCase.Equals(
            $launcherPath, [IO.Path]::GetFullPath($expectedLauncher)
        ) -or
        -not (Test-Path -LiteralPath $launcherPath -PathType Leaf) -or
        (Test-ReparseAtOrAbove $launcherPath) -or
        (Get-Sha256File $launcherPath) -cne [string]$receipt.launcher_sha256 -or
        [IO.Path]::GetFullPath([string]$receipt.updater_path) -cne [IO.Path]::GetFullPath($PSCommandPath)) {
        throw 'INVALID_RECEIPT'
    }
    return Get-Sha256File $receiptPath
}

function Assert-SessionManifest {
    param($Manifest, [string]$Tag, [string]$Version)
    Assert-ExactProperties $Manifest @(
        'schema_version', 'target', 'release_tag', 'base_version', 'tools'
    ) 'INVALID_SESSION_MANIFEST'
    if (-not (Test-ExactInteger $Manifest.schema_version) -or $Manifest.schema_version -ne 1 -or
        [string]$Manifest.target -cne $script:Target -or
        [string]$Manifest.release_tag -cne $Tag -or [string]$Manifest.base_version -cne $Version) {
        throw 'INVALID_SESSION_MANIFEST'
    }
    $tools = @()
    foreach ($item in $Manifest.tools) { $tools += $item }
    if ($tools.Count -ne 1) { throw 'BLOCKED_MULTI_TOOL_ASSET' }
    $tool = $tools[0]
    Assert-ExactProperties $tool @('id', 'files') 'INVALID_SESSION_MANIFEST'
    if ([string]$tool.id -cne 'ru-writing-style' -or
        [string]$tool.id -cnotmatch '^[A-Za-z0-9][A-Za-z0-9-]{0,63}$') { throw 'INVALID_TOOL_ID' }
    $files = @()
    foreach ($item in $tool.files) { $files += $item }
    if ($files.Count -lt 1 -or $files.Count -gt 256) { throw 'INVALID_SESSION_MANIFEST' }
    $seen = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $total = 0L
    $previous = $null
    foreach ($file in $files) {
        Assert-ExactProperties $file @('path', 'sha256', 'bytes') 'INVALID_SESSION_MANIFEST'
        $path = [string]$file.path
        if (-not (Test-ExactInteger $file.bytes)) { throw 'INVALID_SESSION_MANIFEST' }
        $size = [long]$file.bytes
        if ([string]::IsNullOrWhiteSpace($path) -or $path.Contains('\') -or $path.StartsWith('/') -or
            $path.Contains(':') -or @($path.Split('/')) -contains '..' -or @($path.Split('/')) -contains '.' -or
            @($path.Split('/')) -contains '' -or
            [IO.Path]::GetExtension($path).ToLowerInvariant() -notin $script:AllowedExtensions -or
            $size -lt 0 -or $size -gt $script:MaxFileBytes -or -not (Test-LowerSha256 $file.sha256) -or
            -not $seen.Add($path) -or ($null -ne $previous -and [StringComparer]::Ordinal.Compare($previous, $path) -ge 0)) {
            throw 'INVALID_SESSION_MANIFEST'
        }
        $previous = $path
        $total += $size
    }
    if ($total -gt $script:MaxExpandedBytes) { throw 'INVALID_SESSION_MANIFEST' }
    return $tool
}

function Read-SessionArchive {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Asset,
        [Parameter(Mandatory = $true)][string]$Tag,
        [Parameter(Mandatory = $true)][string]$Version
    )
    $metadata = Get-Item -LiteralPath $Path
    if ($metadata.Length -ne [long]$Asset.bytes -or $metadata.Length -gt $script:MaxZipBytes -or
        (Get-Sha256File $Path) -cne [string]$Asset.sha256) { throw 'INVALID_SESSION_ASSET' }
    Add-Type -AssemblyName System.IO.Compression -ErrorAction Stop
    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop
    $archive = [IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $entries = @($archive.Entries)
        if ($entries.Count -gt 257) { throw 'INVALID_SESSION_ASSET' }
        $expanded = ($entries | Measure-Object -Property Length -Sum).Sum
        if ([long]$expanded -gt $script:MaxExpandedBytes) { throw 'INVALID_SESSION_ASSET' }
        $map = @{}
        $case = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        foreach ($entry in $entries) {
            $name = [string]$entry.FullName
            $mode = ([int]$entry.ExternalAttributes -shr 16) -band 0xFFFF
            if ([string]::IsNullOrWhiteSpace($entry.Name) -or $name.Contains('\') -or $name.StartsWith('/') -or
                $name.Contains(':') -or @($name.Split('/')) -contains '..' -or @($name.Split('/')) -contains '.' -or
                @($name.Split('/')) -contains '' -or $map.ContainsKey($name) -or -not $case.Add($name) -or
                ($mode -band 0xF000) -eq 0xA000 -or ($mode -band 73) -ne 0) {
                throw 'INVALID_SESSION_ASSET'
            }
            $map[$name] = $entry
        }
        if (-not $map.ContainsKey('session-tools-manifest.json')) { throw 'INVALID_SESSION_ASSET' }
        $manifestStream = $map['session-tools-manifest.json'].Open()
        try {
            $memory = New-Object IO.MemoryStream
            $manifestStream.CopyTo($memory)
            $manifestBytes = $memory.ToArray()
            $memory.Dispose()
        }
        finally { $manifestStream.Dispose() }
        if ((Get-Sha256Bytes $manifestBytes) -cne [string]$Asset.manifest_sha256) { throw 'INVALID_SESSION_MANIFEST' }
        $manifest = ConvertFrom-StrictJsonBytes $manifestBytes
        $tool = Assert-SessionManifest $manifest $Tag $Version
        $files = @()
        foreach ($item in $tool.files) { $files += $item }
        if (-not (Test-ExactInteger $Asset.tool_count) -or [long]$Asset.tool_count -ne 1) {
            throw 'BLOCKED_MULTI_TOOL_ASSET'
        }
        if (-not (Test-ExactInteger $Asset.file_count) -or [long]$Asset.file_count -ne $files.Count) {
            throw 'INVALID_SESSION_ASSET'
        }
        $expectedNames = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
        [void]$expectedNames.Add('session-tools-manifest.json')
        $payloads = [ordered]@{}
        foreach ($file in $files) {
            $name = 'tools/' + [string]$tool.id + '/' + [string]$file.path
            [void]$expectedNames.Add($name)
            if (-not $map.ContainsKey($name)) { throw 'INVALID_SESSION_ASSET' }
            $stream = $map[$name].Open()
            try {
                $memory = New-Object IO.MemoryStream
                $stream.CopyTo($memory)
                $bytes = $memory.ToArray()
                $memory.Dispose()
            }
            finally { $stream.Dispose() }
            if ($bytes.Length -ne [long]$file.bytes -or (Get-Sha256Bytes $bytes) -cne [string]$file.sha256) {
                throw 'INVALID_SESSION_ASSET'
            }
            $payloads[[string]$file.path] = $bytes
        }
        if ($map.Count -ne $expectedNames.Count) { throw 'INVALID_SESSION_ASSET' }
        foreach ($name in $map.Keys) { if (-not $expectedNames.Contains($name)) { throw 'INVALID_SESSION_ASSET' } }
        return [pscustomobject][ordered]@{
            manifest = $manifest
            manifest_bytes = $manifestBytes
            tool = $tool
            payloads = $payloads
        }
    }
    finally { $archive.Dispose() }
}

function Assert-ReleaseManifest {
    param($Manifest, [string]$Tag, [string]$Version)
    Assert-ExactProperties $Manifest @(
        'schema_version', 'target', 'version', 'tag', 'channel', 'client',
        'foundation_engine_version',
        'foundation_engine_manifest_sha256', 'source', 'asset',
        'package_manifest_sha256', 'components_lock_sha256',
        'session_tools_asset', 'requires', 'acceptance_evidence_sha256',
        'promoted_from_candidate_manifest_sha256'
    ) 'INVALID_RELEASE_MANIFEST'
    if (-not (Test-ExactInteger $Manifest.schema_version) -or $Manifest.schema_version -ne 1 -or
        [string]$Manifest.target -cne $script:Target -or [string]$Manifest.version -cne $Version -or
        [string]$Manifest.tag -cne $Tag -or [string]$Manifest.channel -cne 'stable') {
        throw 'INVALID_RELEASE_MANIFEST'
    }
    Assert-ExactProperties $Manifest.client @('id', 'supported_version') 'INVALID_RELEASE_MANIFEST'
    if ([string]$Manifest.client.id -cne 'codex-cli' -or
        [string]::IsNullOrWhiteSpace([string]$Manifest.client.supported_version)) {
        throw 'INVALID_RELEASE_MANIFEST'
    }
    Assert-ExactProperties $Manifest.source @(
        'repository', 'commit', 'tree', 'transformation'
    ) 'INVALID_RELEASE_MANIFEST'
    if ([string]$Manifest.source.repository -cne ('https://github.com/' + $script:Repository) -or
        [string]$Manifest.source.commit -cnotmatch '^[0-9a-f]{40}$' -or
        [string]$Manifest.source.tree -cnotmatch '^[0-9a-f]{40}$' -or
        [string]$Manifest.source.transformation -cne 'codex-native-v1') {
        throw 'INVALID_RELEASE_MANIFEST'
    }
    Assert-ExactProperties $Manifest.asset @('name', 'sha256', 'bytes') 'INVALID_RELEASE_MANIFEST'
    Assert-ExactProperties $Manifest.session_tools_asset @(
        'name', 'sha256', 'bytes', 'manifest_sha256', 'tool_count', 'file_count'
    ) 'INVALID_RELEASE_MANIFEST'
    Assert-ExactProperties $Manifest.requires @(
        'immutable_release', 'release_attestation',
        'verification_commands'
    ) 'INVALID_RELEASE_MANIFEST'
    foreach ($name in @(
        'foundation_engine_manifest_sha256', 'package_manifest_sha256',
        'components_lock_sha256', 'acceptance_evidence_sha256',
        'promoted_from_candidate_manifest_sha256'
    )) {
        if (-not (Test-LowerSha256 $Manifest.$name)) { throw 'INVALID_RELEASE_MANIFEST' }
    }
    if (-not (Test-LowerSha256 $Manifest.asset.sha256) -or
        -not (Test-ExactInteger $Manifest.asset.bytes) -or [long]$Manifest.asset.bytes -le 0 -or
        [string]$Manifest.asset.name -cne ('codex-base-' + $Version + '.zip') -or
        -not (Test-LowerSha256 $Manifest.session_tools_asset.sha256) -or
        -not (Test-LowerSha256 $Manifest.session_tools_asset.manifest_sha256) -or
        -not (Test-ExactInteger $Manifest.session_tools_asset.bytes) -or
        [long]$Manifest.session_tools_asset.bytes -le 0 -or
        [long]$Manifest.session_tools_asset.bytes -gt $script:MaxZipBytes -or
        -not (Test-ExactInteger $Manifest.session_tools_asset.tool_count) -or
        [long]$Manifest.session_tools_asset.tool_count -ne 1 -or
        -not (Test-ExactInteger $Manifest.session_tools_asset.file_count) -or
        [long]$Manifest.session_tools_asset.file_count -lt 1 -or
        [long]$Manifest.session_tools_asset.file_count -gt 256 -or
        [string]$Manifest.session_tools_asset.name -cne ('session-tools-codex-' + $Version + '.zip') -or
        $Manifest.requires.immutable_release -isnot [bool] -or
        $Manifest.requires.release_attestation -isnot [bool] -or
        $Manifest.requires.immutable_release -ne $true -or
        $Manifest.requires.release_attestation -ne $true -or
        $Manifest.requires.verification_commands -isnot [Array] -or
        @($Manifest.requires.verification_commands).Count -ne 2 -or
        [string]$Manifest.requires.verification_commands[0] -cne
            ('gh release verify ' + $Tag + ' -R ' + $script:Repository) -or
        [string]$Manifest.requires.verification_commands[1] -cne
            ('gh release verify-asset ' + $Tag + ' codex-base-' + $Version + '.zip -R ' + $script:Repository) -or
        [string]$Manifest.foundation_engine_version -cnotmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') {
        if ((Test-ExactInteger $Manifest.session_tools_asset.tool_count) -and
            ([long]$Manifest.session_tools_asset.tool_count) -ne 1) {
            throw 'BLOCKED_MULTI_TOOL_ASSET'
        }
        throw 'INVALID_RELEASE_MANIFEST'
    }
}

function Get-ExpectedDirectoryFingerprint {
    param($Files)
    $rows = New-Object 'Collections.Generic.List[string]'
    foreach ($file in $Files) {
        $rows.Add(([string]$file.path) + [char]0 + ([string]$file.sha256) + "`n")
    }
    $values = $rows.ToArray()
    [Array]::Sort($values, [StringComparer]::Ordinal)
    return Get-Sha256Bytes $script:Utf8NoBom.GetBytes(($values -join ''))
}

function Assert-CurrentState {
    param([string]$Path, [string]$Destination)
    $state = Read-JsonObject $Path
    Assert-ExactProperties $state @(
        'schema_version', 'target', 'release_tag', 'release_version',
        'release_manifest_sha256', 'session_manifest_sha256', 'verified_at', 'tools'
    ) 'BLOCKED_STATE_DRIFT'
    if (-not (Test-ExactInteger $state.schema_version) -or $state.schema_version -ne 1 -or
        $state.target -isnot [string] -or
        [string]$state.target -cne $script:Target -or
        $state.release_tag -isnot [string] -or
        [string]$state.release_tag -cne ('codex-v' + [string]$state.release_version) -or
        $state.release_version -isnot [string] -or
        [string]$state.release_version -cnotmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' -or
        -not (Test-LowerSha256 $state.release_manifest_sha256) -or
        -not (Test-LowerSha256 $state.session_manifest_sha256) -or
        $state.verified_at -isnot [string] -or
        [string]::IsNullOrWhiteSpace([string]$state.verified_at) -or
        $state.tools -isnot [Array]) {
        throw 'BLOCKED_STATE_DRIFT'
    }
    $parsedTime = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse(
        [string]$state.verified_at, [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind, [ref]$parsedTime
    ) -or $parsedTime.Offset -ne [TimeSpan]::Zero) { throw 'BLOCKED_STATE_DRIFT' }
    $tools = @()
    foreach ($item in $state.tools) { $tools += $item }
    if ($tools.Count -ne 1) { throw 'BLOCKED_STATE_DRIFT' }
    $tool = $tools[0]
    Assert-ExactProperties $tool @('id', 'destination', 'ownership_marker', 'files') 'BLOCKED_STATE_DRIFT'
    if ($tool.id -isnot [string] -or [string]$tool.id -cne 'ru-writing-style' -or
        $tool.destination -isnot [string] -or
        [IO.Path]::GetFullPath([string]$tool.destination) -cne [IO.Path]::GetFullPath($Destination) -or
        $tool.ownership_marker -isnot [string] -or
        $tool.files -isnot [Array] -or
        [string]$tool.ownership_marker -cne 'session-tools-v1:codex:ru-writing-style') {
        throw 'BLOCKED_STATE_DRIFT'
    }
    $files = @()
    foreach ($item in $tool.files) { $files += $item }
    if ($files.Count -lt 1 -or $files.Count -gt 256) { throw 'BLOCKED_STATE_DRIFT' }
    $seen = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $previous = $null
    $total = 0L
    foreach ($file in $files) {
        Assert-ExactProperties $file @('path', 'sha256', 'bytes') 'BLOCKED_STATE_DRIFT'
        $path = [string]$file.path
        if ($file.path -isnot [string] -or -not (Test-ExactInteger $file.bytes)) {
            throw 'BLOCKED_STATE_DRIFT'
        }
        $size = [long]$file.bytes
        if ([string]::IsNullOrWhiteSpace($path) -or $path.Contains('\') -or $path.StartsWith('/') -or
            $path.Contains(':') -or @($path.Split('/')) -contains '..' -or
            @($path.Split('/')) -contains '.' -or @($path.Split('/')) -contains '' -or
            [IO.Path]::GetExtension($path).ToLowerInvariant() -notin $script:AllowedExtensions -or
            $size -lt 0 -or $size -gt $script:MaxFileBytes -or
            -not (Test-LowerSha256 $file.sha256) -or -not $seen.Add($path) -or
            ($null -ne $previous -and [StringComparer]::Ordinal.Compare($previous, $path) -ge 0)) {
            throw 'BLOCKED_STATE_DRIFT'
        }
        $actualPath = Join-Path $Destination $path.Replace('/', '\')
        if (-not (Test-Path -LiteralPath $actualPath -PathType Leaf) -or
            (Test-ReparseAtOrAbove $actualPath) -or
            (Get-Item -LiteralPath $actualPath).Length -ne $size) {
            throw 'BLOCKED_STATE_DRIFT'
        }
        $previous = $path
        $total += $size
    }
    if ($total -gt $script:MaxExpandedBytes) { throw 'BLOCKED_STATE_DRIFT' }
    if ((Get-Fingerprint $Destination) -cne (Get-ExpectedDirectoryFingerprint $files)) {
        throw 'BLOCKED_STATE_DRIFT'
    }
    return $state
}

function Test-BaselineOwnership {
    param([string]$UserRoot, [string]$Destination)
    try {
        $baselinePath = Join-Path $UserRoot '.codex\base\runtime\session-tools-baseline.json'
        if (-not (Test-Path -LiteralPath $baselinePath -PathType Leaf)) { return $false }
        $baseline = Read-JsonObject $baselinePath
        $tool = Assert-SessionManifest $baseline ([string]$baseline.release_tag) ([string]$baseline.base_version)
        if ([string]$baseline.release_tag -cne ('codex-v' + [string]$baseline.base_version)) { return $false }
        if ((Get-Fingerprint $Destination) -cne (Get-ExpectedDirectoryFingerprint $tool.files)) { return $false }
        return $true
    }
    catch { return $false }
}

function New-OperationMap {
    return [ordered]@{
        move_destination_to_previous = [ordered]@{ intent = $false; applied = $false }
        move_staging_to_destination = [ordered]@{ intent = $false; applied = $false }
        write_state = [ordered]@{ intent = $false; applied = $false }
    }
}

function Test-Sha256OrAbsent {
    param($Value)
    return [string]$Value -ceq 'absent' -or (Test-LowerSha256 $Value)
}

function Test-PathEqual {
    param([string]$Left, [string]$Right)
    if ([string]::IsNullOrWhiteSpace($Left) -or [string]::IsNullOrWhiteSpace($Right)) { return $false }
    return [StringComparer]::OrdinalIgnoreCase.Equals(
        [IO.Path]::GetFullPath($Left), [IO.Path]::GetFullPath($Right)
    )
}

function Assert-Journal {
    param($Journal, [string]$StateRoot, [string]$UserRoot, $Clock, [string]$ReceiptSha)
    Assert-ExactProperties $Journal @(
        'schema_version', 'target', 'transaction_id', 'phase', 'receipt_sha256',
        'start_tick', 'mutation_cutoff_tick', 'kill_tick', 'hard_deadline_tick',
        'stopwatch_frequency', 'previous_destination_sha256', 'previous_state_sha256',
        'expected_staging_sha256', 'expected_destination_sha256', 'expected_state_sha256',
        'staging_path', 'previous_path', 'destination_path', 'state_path', 'operations'
    ) 'BLOCKED_SESSION_RECOVERY'
    $phases = @(
        'created', 'staged', 'move_destination_intent', 'move_destination_applied',
        'move_staging_intent', 'move_staging_applied', 'state_write_intent',
        'state_write_applied', 'committed'
    )
    $parsed = [Guid]::Empty
    if (-not (Test-ExactInteger $Journal.schema_version) -or $Journal.schema_version -ne 1 -or
        [string]$Journal.target -cne $script:Target -or
        -not [Guid]::TryParseExact([string]$Journal.transaction_id, 'D', [ref]$parsed) -or
        $parsed.ToString('D') -cne [string]$Journal.transaction_id -or
        $Journal.phase -isnot [string] -or $phases -cnotcontains [string]$Journal.phase -or
        [string]$Journal.receipt_sha256 -cne $ReceiptSha) {
        throw 'BLOCKED_SESSION_RECOVERY'
    }
    foreach ($name in @(
        'start_tick', 'mutation_cutoff_tick', 'kill_tick', 'hard_deadline_tick',
        'stopwatch_frequency'
    )) {
        if (-not (Test-ExactInteger $Journal.$name) -or [long]$Journal.$name -le 0) {
            throw 'BLOCKED_SESSION_RECOVERY'
        }
    }
    $frequency = [long]$Journal.stopwatch_frequency
    $start = [long]$Journal.start_tick
    if ($frequency -ne [Diagnostics.Stopwatch]::Frequency -or
        $frequency -gt [long]::MaxValue / 30 -or
        $start -gt [long]::MaxValue - (30 * $frequency) -or
        [long]$Journal.mutation_cutoff_tick -ne $start + (22 * $frequency) -or
        [long]$Journal.kill_tick -ne $start + (25 * $frequency) -or
        [long]$Journal.hard_deadline_tick -ne $start + (30 * $frequency) -or
        [long]$Journal.hard_deadline_tick -gt [long]$Clock.hard_deadline_tick) {
        throw 'BLOCKED_SESSION_RECOVERY'
    }
    foreach ($name in @(
        'previous_destination_sha256', 'previous_state_sha256', 'expected_staging_sha256',
        'expected_destination_sha256', 'expected_state_sha256'
    )) {
        if (-not (Test-Sha256OrAbsent $Journal.$name)) { throw 'BLOCKED_SESSION_RECOVERY' }
    }
    $operationNames = @(
        'move_destination_to_previous', 'move_staging_to_destination', 'write_state'
    )
    Assert-ExactProperties $Journal.operations $operationNames 'BLOCKED_SESSION_RECOVERY'
    $actualFlags = New-Object 'Collections.Generic.List[bool]'
    foreach ($name in $operationNames) {
        $operation = $Journal.operations.$name
        Assert-ExactProperties $operation @('intent', 'applied') 'BLOCKED_SESSION_RECOVERY'
        if ($operation.intent -isnot [bool] -or $operation.applied -isnot [bool] -or
            ($operation.applied -and -not $operation.intent)) {
            throw 'BLOCKED_SESSION_RECOVERY'
        }
        $actualFlags.Add([bool]$operation.intent)
        $actualFlags.Add([bool]$operation.applied)
    }
    [bool[]]$expectedFlags = @($false, $false, $false, $false, $false, $false)
    $enabled = [Array]::IndexOf($phases, [string]$Journal.phase)
    if ($enabled -ge 2) {
        $transition = $enabled - 2
        for ($index = 0; $index -le $transition -and $index -lt $expectedFlags.Count; $index++) {
            $expectedFlags[$index] = $true
        }
    }
    if ([string]$Journal.phase -ceq 'committed') {
        for ($index = 0; $index -lt $expectedFlags.Count; $index++) { $expectedFlags[$index] = $true }
    }
    for ($index = 0; $index -lt $expectedFlags.Count; $index++) {
        if ($actualFlags[$index] -ne $expectedFlags[$index]) { throw 'BLOCKED_SESSION_RECOVERY' }
    }
    $transactionRoot = Join-Path (Join-Path $StateRoot 'transactions') $parsed.ToString('D')
    $skillsRoot = Join-Path $UserRoot '.agents\skills'
    if (-not (Test-PathEqual $Journal.staging_path (Join-Path $transactionRoot 'staging')) -or
        -not (Test-PathEqual $Journal.previous_path (Join-Path $transactionRoot 'previous')) -or
        -not (Test-PathEqual $Journal.state_path (Join-Path $StateRoot 'state.json')) -or
        [string]::IsNullOrWhiteSpace([string]$Journal.destination_path) -or
        -not [IO.Path]::IsPathRooted([string]$Journal.destination_path) -or
        -not [StringComparer]::OrdinalIgnoreCase.Equals(
            [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath([string]$Journal.destination_path)),
            [IO.Path]::GetFullPath($skillsRoot)
        )) {
        throw 'BLOCKED_SESSION_RECOVERY'
    }
    foreach ($path in @(
        $transactionRoot, $Journal.staging_path, $Journal.previous_path,
        $Journal.destination_path, $Journal.state_path
    )) {
        if (Test-ReparseAtOrAbove ([string]$path)) { throw 'BLOCKED_SESSION_RECOVERY' }
    }
}

function Test-JournalLayout {
    param(
        [int]$Step, [string]$DestinationNow, [string]$PreviousNow,
        [string]$StagingNow, [string]$StateNow, [string]$OldDestination,
        [string]$ExpectedStaging, [string]$NewDestination,
        [string]$OldState, [string]$NewState
    )
    $destinationExpected = if ($Step -ge 2) { $NewDestination } elseif ($Step -ge 1) { 'absent' } else { $OldDestination }
    $previousExpected = if ($Step -ge 1) { $OldDestination } else { 'absent' }
    $stagingExpected = if ($Step -ge 2) { 'absent' } else { $ExpectedStaging }
    $stateExpected = if ($Step -ge 3) { $NewState } else { $OldState }
    return $DestinationNow -ceq $destinationExpected -and
        $PreviousNow -ceq $previousExpected -and $StagingNow -ceq $stagingExpected -and
        $StateNow -ceq $stateExpected
}

function Remove-SafeEntry {
    param([string]$Path, [long]$Deadline = [long]::MaxValue)
    if ([Diagnostics.Stopwatch]::GetTimestamp() -ge $Deadline) { throw 'RECOVERY_TIMEOUT' }
    if (-not (Test-Path -LiteralPath $Path)) { return }
    [void]@(Get-SafeTreeFiles $Path)
    if (Test-Path -LiteralPath $Path -PathType Container) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    else { Remove-Item -LiteralPath $Path -Force }
    if ([Diagnostics.Stopwatch]::GetTimestamp() -ge $Deadline) { throw 'RECOVERY_TIMEOUT' }
}

function Remove-SafeCreatedStaging {
    param([string]$Path, [long]$Deadline)
    if ([Diagnostics.Stopwatch]::GetTimestamp() -ge $Deadline) { throw 'RECOVERY_TIMEOUT' }
    if ([IO.File]::Exists($Path)) { throw 'BLOCKED_SESSION_RECOVERY' }
    if (-not [IO.Directory]::Exists($Path)) {
        if (Test-Path -LiteralPath $Path) { throw 'BLOCKED_SESSION_RECOVERY' }
        return
    }
    [void]@(Get-SafeTreeFiles $Path)
    if ([IO.File]::Exists($Path) -or -not [IO.Directory]::Exists($Path)) {
        throw 'BLOCKED_SESSION_RECOVERY'
    }
    [void]@(Get-SafeTreeFiles $Path)
    if ([Diagnostics.Stopwatch]::GetTimestamp() -ge $Deadline) { throw 'RECOVERY_TIMEOUT' }
    Remove-Item -LiteralPath $Path -Recurse -Force
    if ([Diagnostics.Stopwatch]::GetTimestamp() -ge $Deadline) { throw 'RECOVERY_TIMEOUT' }
}

function Invoke-JournalRecovery {
    param([string]$StateRoot, [string]$UserRoot, $Clock, [string]$ReceiptSha)
    $journalPath = Join-Path $StateRoot 'active-transaction.json'
    if (-not (Test-Path -LiteralPath $journalPath -PathType Leaf)) { return $true }
    try {
        $journal = Read-JsonObject $journalPath
        Assert-Journal $journal $StateRoot $UserRoot $Clock $ReceiptSha
        if ([Diagnostics.Stopwatch]::GetTimestamp() -ge [long]$Clock.hard_deadline_tick) {
            throw 'RECOVERY_TIMEOUT'
        }
        $destinationNow = Get-Fingerprint ([string]$journal.destination_path)
        $previousNow = Get-Fingerprint ([string]$journal.previous_path)
        $stagingNow = Get-Fingerprint ([string]$journal.staging_path)
        $stateNow = Get-Fingerprint ([string]$journal.state_path)
        $oldDestination = [string]$journal.previous_destination_sha256
        $expectedStaging = [string]$journal.expected_staging_sha256
        $newDestination = [string]$journal.expected_destination_sha256
        $oldState = [string]$journal.previous_state_sha256
        $newState = [string]$journal.expected_state_sha256
        $actualStep = -1
        if ([string]$journal.phase -ceq 'created') {
            if ($destinationNow -cne $oldDestination -or $previousNow -cne 'absent' -or
                $stateNow -cne $oldState -or
                (Test-Path -LiteralPath ([string]$journal.staging_path) -PathType Leaf)) {
                throw 'BLOCKED_SESSION_RECOVERY'
            }
            $actualStep = 0
        }
        else {
            $durableStep = if ([bool]$journal.operations.write_state.applied) { 3 } elseif (
                [bool]$journal.operations.move_staging_to_destination.applied
            ) { 2 } elseif ([bool]$journal.operations.move_destination_to_previous.applied) { 1 } else { 0 }
            $maximumStep = if ([string]$journal.phase -clike '*_intent') { $durableStep + 1 } else { $durableStep }
            for ($candidate = $maximumStep; $candidate -ge $durableStep; $candidate--) {
                if (Test-JournalLayout $candidate $destinationNow $previousNow $stagingNow $stateNow `
                    $oldDestination $expectedStaging $newDestination $oldState $newState) {
                    $actualStep = $candidate
                    break
                }
            }
        }
        if ($actualStep -lt 0) { throw 'BLOCKED_SESSION_RECOVERY' }
        if ($actualStep -eq 3) {
            Remove-SafeEntry ([string]$journal.previous_path) ([long]$Clock.hard_deadline_tick)
        }
        else {
            if ($actualStep -ge 2) {
                Remove-SafeEntry ([string]$journal.destination_path) ([long]$Clock.hard_deadline_tick)
            }
            if ($actualStep -ge 1 -and $oldDestination -cne 'absent') {
                if ([Diagnostics.Stopwatch]::GetTimestamp() -ge [long]$Clock.hard_deadline_tick) {
                    throw 'RECOVERY_TIMEOUT'
                }
                [IO.Directory]::Move([string]$journal.previous_path, [string]$journal.destination_path)
                if ([Diagnostics.Stopwatch]::GetTimestamp() -ge [long]$Clock.hard_deadline_tick) {
                    throw 'RECOVERY_TIMEOUT'
                }
            }
        }
        if ($actualStep -eq 0 -and [string]$journal.phase -ceq 'created') {
            Remove-SafeCreatedStaging `
                ([string]$journal.staging_path) `
                ([long]$Clock.hard_deadline_tick)
        }
        else {
            Remove-SafeEntry ([string]$journal.staging_path) ([long]$Clock.hard_deadline_tick)
        }
        $finalDestination = if ($actualStep -eq 3) { $newDestination } else { $oldDestination }
        $finalState = if ($actualStep -eq 3) { $newState } else { $oldState }
        if ((Get-Fingerprint ([string]$journal.destination_path)) -cne $finalDestination -or
            (Get-Fingerprint ([string]$journal.state_path)) -cne $finalState -or
            (Get-Fingerprint ([string]$journal.previous_path)) -cne 'absent' -or
            (Get-Fingerprint ([string]$journal.staging_path)) -cne 'absent') {
            throw 'BLOCKED_SESSION_RECOVERY'
        }
        if ([Diagnostics.Stopwatch]::GetTimestamp() -ge [long]$Clock.hard_deadline_tick) {
            throw 'RECOVERY_TIMEOUT'
        }
        $transactionRoot = Split-Path -Parent ([string]$journal.staging_path)
        if (Test-Path -LiteralPath $transactionRoot -PathType Container) {
            try { [IO.Directory]::Delete($transactionRoot, $false) } catch { }
        }
        [IO.File]::Delete($journalPath)
        if ([Diagnostics.Stopwatch]::GetTimestamp() -ge [long]$Clock.hard_deadline_tick) {
            throw 'RECOVERY_TIMEOUT'
        }
        return $true
    }
    catch { return $false }
}

function Write-Journal {
    param([string]$Path, $Journal)
    Write-DurableJson $Path $Journal
}

function Set-JournalPhase {
    param([string]$Path, $Journal, [string]$Phase)
    $Journal.phase = $Phase
    Write-Journal $Path $Journal
}

function Write-ResultLog {
    param([string]$StateRoot, [string]$Tag, [string]$Result, [string]$Reason)
    try {
        [IO.Directory]::CreateDirectory($StateRoot) | Out-Null
        $line = [ordered]@{
            target = $script:Target
            tag = $Tag
            result = $Result
            reason = $Reason
        } | ConvertTo-Json -Compress
        [IO.File]::AppendAllText((Join-Path $StateRoot 'update.log'), $line + "`n", $script:Utf8NoBom)
    }
    catch { }
}

function Invoke-Update {
    param($Clock)
    $userRoot = [IO.Path]::GetFullPath($env:USERPROFILE)
    $stateRoot = Join-Path $userRoot '.llm-foundation\state\session-tools\codex'
    $journalPath = Join-Path $stateRoot 'active-transaction.json'
    $receiptSha = Get-ReceiptHash $userRoot
    if (-not (Invoke-JournalRecovery $stateRoot $userRoot $Clock $receiptSha)) {
        throw 'BLOCKED_SESSION_RECOVERY'
    }
    if ([Diagnostics.Stopwatch]::GetTimestamp() -ge [long]$Clock.mutation_cutoff_tick) {
        Write-ResultLog $stateRoot '' 'SKIPPED_DEADLINE' 'clock'
        return $false
    }
    $ghCommand = Get-Command gh -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $ghCommand -or
        -not (Test-Path -LiteralPath ([string]$ghCommand.Source) -PathType Leaf) -or
        (Test-ReparseAtOrAbove ([string]$ghCommand.Source))) {
        Write-ResultLog $stateRoot '' 'BLOCKED_GH_REQUIRED' 'gh'
        return $false
    }
    $gh = [string]$ghCommand.Source
    $listText = Invoke-External $gh @(
        'release', 'list', '-R', $script:Repository, '--limit', '20',
        '--json', 'tagName,isDraft,isPrerelease,publishedAt'
    ) ([long]$Clock.mutation_cutoff_tick)
    $releaseValue = ConvertFrom-StrictJsonBytes $script:Utf8NoBom.GetBytes($listText)
    $releases = @()
    foreach ($item in $releaseValue) { $releases += $item }
    $stable = @()
    foreach ($release in $releases) {
        Assert-ExactProperties $release @(
            'tagName', 'isDraft', 'isPrerelease', 'publishedAt'
        ) 'INVALID_RELEASE_LIST'
        if ($release.isDraft -isnot [bool] -or $release.isPrerelease -isnot [bool] -or
            [string]$release.tagName -cnotmatch '^codex-v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' -or
            [string]::IsNullOrWhiteSpace([string]$release.publishedAt)) {
            throw 'INVALID_RELEASE_LIST'
        }
        if (-not $release.isDraft -and -not $release.isPrerelease -and
            [string]$release.tagName -cmatch '^codex-v([0-9]+\.[0-9]+\.[0-9]+)$') {
            $stable += [pscustomobject]@{ tag = [string]$release.tagName; version = [version]$Matches[1] }
        }
    }
    if ($stable.Count -eq 0) {
        Write-ResultLog $stateRoot '' 'NO_STABLE_RELEASE' 'release'
        return $false
    }
    $latest = $stable | Sort-Object -Property version -Descending | Select-Object -First 1
    $statePath = Join-Path $stateRoot 'state.json'
    $destination = Join-Path $userRoot '.agents\skills\ru-writing-style'
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        $current = Assert-CurrentState $statePath $destination
        $currentVersion = [version][string]$current.release_version
        if ($currentVersion -ge $latest.version) {
            Write-ResultLog $stateRoot ([string]$latest.tag) 'NO_UPDATE' 'current'
            return $false
        }
    }

    $downloadRoot = Join-Path ([IO.Path]::GetTempPath()) ('codex-session-tools-' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($downloadRoot) | Out-Null
    try {
        [void](Invoke-External $gh @('release', 'verify', [string]$latest.tag, '-R', $script:Repository) ([long]$Clock.mutation_cutoff_tick))
        [void](Invoke-External $gh @(
            'release', 'download', [string]$latest.tag, '-R', $script:Repository,
            '--dir', $downloadRoot, '--pattern', 'release-manifest.json',
            '--pattern', ('session-tools-codex-' + $latest.version.ToString() + '.zip')
        ) ([long]$Clock.mutation_cutoff_tick))
        $releasePath = Join-Path $downloadRoot 'release-manifest.json'
        $assetPath = Join-Path $downloadRoot ('session-tools-codex-' + $latest.version.ToString() + '.zip')
        foreach ($path in @($releasePath, $assetPath)) {
            [void](Invoke-External $gh @('release', 'verify-asset', [string]$latest.tag, $path, '-R', $script:Repository) ([long]$Clock.mutation_cutoff_tick))
            [void](Invoke-External $gh @('attestation', 'verify', $path, '--repo', $script:Repository) ([long]$Clock.mutation_cutoff_tick))
        }
        $release = Read-JsonObject $releasePath
        $versionText = $latest.version.ToString()
        Assert-ReleaseManifest $release ([string]$latest.tag) $versionText
        $bundle = Read-SessionArchive $assetPath $release.session_tools_asset ([string]$latest.tag) $versionText
        if ([Diagnostics.Stopwatch]::GetTimestamp() -ge [long]$Clock.mutation_cutoff_tick) { throw 'DEADLINE_REACHED' }

        $tool = $bundle.tool
        $destination = Join-Path $userRoot ('.agents\skills\' + [string]$tool.id)
        $previousDestinationHash = Get-Fingerprint $destination
        if ($previousDestinationHash -ne 'absent' -and -not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
            if (-not (Test-BaselineOwnership $userRoot $destination)) {
                throw 'BLOCKED_UNMANAGED_COLLISION'
            }
        }
        $transactionRoot = Join-Path $stateRoot ('transactions\' + [string]$Clock.transaction_id)
        $staging = Join-Path $transactionRoot 'staging'
        $previous = Join-Path $transactionRoot 'previous'
        $previousStateHash = Get-Fingerprint $statePath
        $verifiedAt = [DateTimeOffset]::UtcNow.ToString('o')
        $stateValue = [ordered]@{
            schema_version = 1
            target = $script:Target
            release_tag = [string]$latest.tag
            release_version = $versionText
            release_manifest_sha256 = Get-Sha256File $releasePath
            session_manifest_sha256 = Get-Sha256Bytes $bundle.manifest_bytes
            verified_at = $verifiedAt
            tools = @(
                [ordered]@{
                    id = [string]$tool.id
                    destination = [IO.Path]::GetFullPath($destination)
                    ownership_marker = 'session-tools-v1:codex:' + [string]$tool.id
                    files = @($tool.files)
                }
            )
        }
        $stateBytes = ConvertTo-JsonBytes $stateValue
        $expectedStateHash = Get-Sha256Bytes $stateBytes
        $expectedDestinationHash = Get-ExpectedDirectoryFingerprint $tool.files
        $journal = [ordered]@{
            schema_version = 1
            target = $script:Target
            transaction_id = [string]$Clock.transaction_id
            phase = 'created'
            receipt_sha256 = $receiptSha
            start_tick = [long]$Clock.start_tick
            mutation_cutoff_tick = [long]$Clock.mutation_cutoff_tick
            kill_tick = [long]$Clock.kill_tick
            hard_deadline_tick = [long]$Clock.hard_deadline_tick
            stopwatch_frequency = [long]$Clock.stopwatch_frequency
            previous_destination_sha256 = $previousDestinationHash
            previous_state_sha256 = $previousStateHash
            expected_staging_sha256 = $expectedDestinationHash
            expected_destination_sha256 = $expectedDestinationHash
            expected_state_sha256 = $expectedStateHash
            staging_path = [IO.Path]::GetFullPath($staging)
            previous_path = [IO.Path]::GetFullPath($previous)
            destination_path = [IO.Path]::GetFullPath($destination)
            state_path = [IO.Path]::GetFullPath($statePath)
            operations = New-OperationMap
        }
        if ([Diagnostics.Stopwatch]::GetTimestamp() -ge [long]$Clock.mutation_cutoff_tick) {
            throw 'DEADLINE_REACHED'
        }
        Write-Journal $journalPath $journal
        try {
            if ([Diagnostics.Stopwatch]::GetTimestamp() -ge [long]$Clock.mutation_cutoff_tick) {
                throw 'DEADLINE_REACHED'
            }
            [IO.Directory]::CreateDirectory($staging) | Out-Null
            foreach ($relative in $bundle.payloads.Keys) {
                if ([Diagnostics.Stopwatch]::GetTimestamp() -ge [long]$Clock.mutation_cutoff_tick) {
                    throw 'DEADLINE_REACHED'
                }
                $path = Join-Path $staging ([string]$relative).Replace('/', '\')
                [IO.Directory]::CreateDirectory((Split-Path -Parent $path)) | Out-Null
                [IO.File]::WriteAllBytes($path, [byte[]]$bundle.payloads[$relative])
            }
            if ((Get-Fingerprint $staging) -cne $expectedDestinationHash) { throw 'STAGING_MISMATCH' }
            Set-JournalPhase $journalPath $journal 'staged'
            if ([Diagnostics.Stopwatch]::GetTimestamp() -ge [long]$Clock.mutation_cutoff_tick) { throw 'DEADLINE_REACHED' }

            $journal.operations.move_destination_to_previous.intent = $true
            Set-JournalPhase $journalPath $journal 'move_destination_intent'
            if ([Diagnostics.Stopwatch]::GetTimestamp() -ge [long]$Clock.mutation_cutoff_tick) {
                throw 'DEADLINE_REACHED'
            }
            if (Test-Path -LiteralPath $destination) { [IO.Directory]::Move($destination, $previous) }
            $journal.operations.move_destination_to_previous.applied = $true
            Set-JournalPhase $journalPath $journal 'move_destination_applied'

            $journal.operations.move_staging_to_destination.intent = $true
            Set-JournalPhase $journalPath $journal 'move_staging_intent'
            [IO.Directory]::CreateDirectory((Split-Path -Parent $destination)) | Out-Null
            [IO.Directory]::Move($staging, $destination)
            $journal.operations.move_staging_to_destination.applied = $true
            Set-JournalPhase $journalPath $journal 'move_staging_applied'

            $journal.operations.write_state.intent = $true
            Set-JournalPhase $journalPath $journal 'state_write_intent'
            Write-DurableBytes $statePath $stateBytes
            $journal.operations.write_state.applied = $true
            Set-JournalPhase $journalPath $journal 'state_write_applied'
            Set-JournalPhase $journalPath $journal 'committed'

            Remove-SafeEntry $previous
            if (Test-Path -LiteralPath $transactionRoot -PathType Container) {
                try { [IO.Directory]::Delete($transactionRoot, $false) } catch { }
            }
            [IO.File]::Delete($journalPath)
        }
        catch {
            if ([Diagnostics.Stopwatch]::GetTimestamp() -lt [long]$Clock.kill_tick) {
                [void](Invoke-JournalRecovery $stateRoot $userRoot $Clock $receiptSha)
            }
            throw
        }
        Write-ResultLog $stateRoot ([string]$latest.tag) 'UPDATED' 'verified'
        return $true
    }
    finally {
        if (Test-Path -LiteralPath $downloadRoot -PathType Container) {
            Remove-Item -LiteralPath $downloadRoot -Recurse -Force
        }
    }
}

try {
    $clock = Get-ClockContract
    $userRoot = [IO.Path]::GetFullPath($env:USERPROFILE)
    $stateRoot = Join-Path $userRoot '.llm-foundation\state\session-tools\codex'
    [IO.Directory]::CreateDirectory($stateRoot) | Out-Null
    $lockPath = Join-Path $stateRoot 'update.lock'
    $lockDeadline = [Math]::Min(
        [long]$clock.mutation_cutoff_tick,
        [Diagnostics.Stopwatch]::GetTimestamp() + [long]$clock.stopwatch_frequency
    )
    $targetLock = $null
    while ($null -eq $targetLock -and [Diagnostics.Stopwatch]::GetTimestamp() -lt $lockDeadline) {
        try {
            $targetLock = New-Object IO.FileStream(
                $lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite,
                [IO.FileShare]::None
            )
        }
        catch [IO.IOException] { Start-Sleep -Milliseconds 100 }
    }
    if ($null -eq $targetLock) {
        Write-ResultLog $stateRoot '' 'SKIPPED_LOCK_BUSY' 'lock'
        exit 0
    }
    try { $updated = Invoke-Update $clock }
    finally { $targetLock.Dispose() }
    if ($HookFallback -and $updated) { Write-Output 'TOOLS_APPLIED_NEXT_SESSION' }
    exit 0
}
catch {
    if ($ManagedPreflight -and $_.Exception.Message -match '^(INVALID_MODE|INVALID_TRANSACTION_ID|INVALID_CLOCK_CONTRACT)$') {
        [Console]::Error.WriteLine($_.Exception.Message)
        exit 2
    }
    if ($ManagedPreflight) {
        try {
            $activeRoot = Join-Path ([IO.Path]::GetFullPath($env:USERPROFILE)) '.llm-foundation\state\session-tools\codex'
            if (Test-Path -LiteralPath (Join-Path $activeRoot 'active-transaction.json') -PathType Leaf) {
                [Console]::Error.WriteLine('BLOCKED_SESSION_RECOVERY')
                exit 65
            }
        }
        catch { }
    }
    try {
        $userRoot = [IO.Path]::GetFullPath($env:USERPROFILE)
        $stateRoot = Join-Path $userRoot '.llm-foundation\state\session-tools\codex'
        $reason = [string]$_.Exception.Message
        if ($reason -cnotmatch '^[A-Z][A-Z0-9_]{0,63}$') { $reason = 'unexpected' }
        Write-ResultLog $stateRoot '' 'BLOCKED' $reason
    }
    catch { }
    exit 0
}
