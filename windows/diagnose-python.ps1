# ASCII-only Windows PowerShell 5.1 compatible diagnostics; read-only.
param([switch]$Show)
$ErrorActionPreference = 'Continue'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Target = Join-Path $env:LOCALAPPDATA 'DocForge'
$Cache = Join-Path $env:LOCALAPPDATA 'DocForge-InstallCache'
New-Item -ItemType Directory -Path $Cache -Force | Out-Null
$Report = Join-Path $Cache 'python-diagnostics.txt'
$Probe = Join-Path $PSScriptRoot 'probe_python.py'
$results = New-Object System.Collections.Generic.List[string]
function Line([string]$s) { $script:results.Add($s) }
Line ('DocForge Python diagnostics; ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Line ('PowerShell version: ' + $PSVersionTable.PSVersion.ToString())
Line ('OS bitness: ' + [Environment]::Is64BitOperatingSystem + '; PS bitness: ' + [Environment]::Is64BitProcess)
Line ('Install folder: ' + $Target)
Line ('Probe exists: ' + (Test-Path -LiteralPath $Probe -PathType Leaf))
$candidates = New-Object System.Collections.Generic.List[string]
$candidates.Add((Join-Path $Target 'venv313\Scripts\python.exe'))
$candidates.Add((Join-Path $Target 'runtime\python313\python.exe'))
$candidates.Add((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'))
$candidates.Add((Join-Path $env:ProgramFiles 'Python313\python.exe'))
$cfg = Join-Path $Target 'venv313\pyvenv.cfg'
if (Test-Path -LiteralPath $cfg -PathType Leaf) {
    Line 'pyvenv.cfg found; recorded base Python:'
    foreach ($line in (Get-Content -LiteralPath $cfg)) {
        if ($line -match '^\s*(home|executable|version)\s*=\s*(.*?)\s*$') {
            Line ('  ' + $line)
            if ($Matches[1] -eq 'executable') { $candidates.Add($Matches[2].Trim().Trim('"')) }
            if ($Matches[1] -eq 'home') { $candidates.Add((Join-Path $Matches[2].Trim().Trim('"') 'python.exe')) }
        }
    }
}
foreach ($hive in @('HKCU:', 'HKLM:')) {
    foreach ($version in @('3.13', '3.13-64')) {
        foreach ($prefix in @('Software\Python\PythonCore', 'Software\WOW6432Node\Python\PythonCore')) {
            $key = $hive + '\' + $prefix + '\' + $version + '\InstallPath'
            try {
                $item = Get-Item -LiteralPath $key -ErrorAction Stop
                foreach ($v in @($item.GetValue(''), $item.GetValue('ExecutablePath'))) {
                    if ([string]::IsNullOrWhiteSpace($v)) { continue }
                    if ($v.EndsWith('.exe')) { $candidates.Add([string]$v) }
                    else { $candidates.Add((Join-Path ([string]$v) 'python.exe')) }
                }
            } catch {}
        }
    }
}
try {
    $launch = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launch) {
        Line 'Python Launcher registrations:'
        Line ((& $launch.Source -0p 2>&1 | Out-String).Trim())
    }
} catch { Line ('Launcher check failed: ' + $_.Exception.Message) }
foreach ($cmd in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
    if ($cmd -and $cmd.Source) { $candidates.Add($cmd.Source) }
}
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    Line ''
    Line ('Candidate: ' + $candidate)
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        Line '  FILE MISSING'
        continue
    }
    try {
        $output = & $candidate $Probe --diagnose 2>&1
        $exit = $LASTEXITCODE
        Line ('  exit=' + $exit)
        Line ('  result=' + (($output | Out-String).Trim()))
    } catch { Line ('  LAUNCH ERROR: ' + $_.Exception.Message) }
}
$setupLog = Join-Path $Cache 'python-setup.log'
if (Test-Path -LiteralPath $setupLog -PathType Leaf) {
    Line ''
    Line 'Python Installer log (last 60 lines):'
    foreach ($line in (Get-Content -LiteralPath $setupLog -Tail 60)) { Line $line }
} else { Line 'Python Installer log is missing.' }
[System.IO.File]::WriteAllLines($Report, $results.ToArray(), [System.Text.UTF8Encoding]::new($true))
Write-Host ('[DocForge] Diagnostic report saved: ' + $Report)
if ($Show) { Write-Host ($results -join [Environment]::NewLine) }
