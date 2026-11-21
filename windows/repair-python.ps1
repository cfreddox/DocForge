# Recovery for a registered but broken CPython 3.13.12 Windows install.
# Uses official Repair mode; does not uninstall Python or delete DocForge.
$ErrorActionPreference = 'Stop'
$Cache = Join-Path $env:LOCALAPPDATA 'DocForge-InstallCache'
$Setup = Join-Path $Cache 'python-3.13.12-amd64.exe'
$Report = Join-Path $Cache 'python-repair.log'
$Probe = Join-Path $PSScriptRoot 'probe_python.py'
$DefaultPython = Join-Path $env:LOCALAPPDATA 'DocForge\runtime\python313\python.exe'
if (-not (Test-Path -LiteralPath $Setup -PathType Leaf)) {
    Write-Host ('Cannot find cached installer: ' + $Setup)
    exit 2
}
$signature = Get-AuthenticodeSignature -FilePath $Setup
if ($signature.Status -ne 'Valid') {
    Write-Host 'Python installer is not Authenticode-verified; repair cancelled.'
    exit 3
}
Write-Host 'This uses official Python 3.13.12 Repair mode.'
Write-Host 'It may repair an existing Python 3.13 installation used by other apps.'
Write-Host 'No DocForge settings or user documents will be deleted.'
$answer = Read-Host 'Continue? Type YES'
if ($answer -ne 'YES') { Write-Host 'Cancelled'; exit 1 }
$arguments = '/repair /quiet /norestart /log "' + $Report + '"'
$proc = Start-Process -FilePath $Setup -ArgumentList $arguments -Wait -PassThru
Write-Host ('Repair finished, code: ' + $proc.ExitCode)
Write-Host ('Repair log: ' + $Report)
$diagnose = Join-Path $PSScriptRoot 'diagnose-python.ps1'
if (Test-Path -LiteralPath $diagnose) { & $diagnose }
if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 3010) { exit 4 }
Write-Host 'Now run INSTALL-WINDOWS.cmd to finish the DocForge setup.'
exit 0
