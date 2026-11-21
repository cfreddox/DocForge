# Builds an actual EXE-based offline Windows installer using Python, PyInstaller and Inno Setup.
# Must run on Windows 10/11 x64 or GitHub Actions windows-latest, NOT Linux.
param([string]$Compiler = '', [switch]$SelfTest)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Root
function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )
    Write-Host ('[DocForge Build] Running: ' + $Executable + ' ' + ($ArgumentList -join ' '))
    & $Executable @ArgumentList
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw ('Build command exited with code ' + $exitCode + ': ' + $Executable + ' ' + ($ArgumentList -join ' '))
    }
}

# Runs on the real Windows runner before installing any build dependencies.
# Catches accidental loss of command-line arguments in PowerShell wrappers.
if ($SelfTest) {
    $pythonForTest = (Get-Command python -ErrorAction Stop).Source
    $observed = Invoke-Checked -Executable $pythonForTest -ArgumentList @(
        '-c', 'import sys; print(len(sys.argv))', 'first', 'second'
    )
    if (([string]($observed | Out-String)).Trim() -ne '3') {
        throw ('Native command arguments were not forwarded: expected 3, got ' + $observed)
    }
    Write-Host '[DocForge Build] PASS: native command arguments forwarded correctly.'
    return
}
$Python = (Get-Command python -ErrorAction Stop).Source
Invoke-Checked -Executable $Python -ArgumentList @('-m','pip','install','--disable-pip-version-check','-r','windows\requirements-windows.txt')
Invoke-Checked -Executable $Python -ArgumentList @('-m','pip','install','--disable-pip-version-check','pyinstaller>=6.10,<7')
# Fonts and platform-native deps must be bundled by PyInstaller.
Invoke-Checked -Executable $Python -ArgumentList @('-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed',
    '--name','DocForge','--icon','windows\docforge.ico','--paths','.',
    '--collect-submodules','docforge','--collect-all','PIL','--collect-all','pymupdf','--collect-all','fitz',
    '--collect-all','tkinterdnd2','--collect-all','PySide6','--collect-all','office2pdf',
    '--hidden-import','docforge.pdf_editor','--hidden-import','docforge.word_ui',
    '--hidden-import','docforge.windows_tray','--add-data','assets;assets','windows\launcher.py')
$Dist=Join-Path $Root 'dist\DocForge'
if (-not (Test-Path -LiteralPath (Join-Path $Dist 'DocForge.exe') -PathType Leaf)) {
    throw 'PyInstaller exited successfully but dist\DocForge\DocForge.exe is missing. See PyInstaller output above.'
}
Copy-Item -LiteralPath 'windows\docforge-zone.ico' -Destination $Dist -Force
# Pandoc is shipped inside the offline installer; installed users need no separate download.
$PandocVersion='3.14'
$Zip=Join-Path $env:TEMP ('docforge-pandoc-' + $PandocVersion + '.zip')
if (-not (Test-Path -LiteralPath $Zip)) {
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 1200 -Uri ('https://github.com/jgm/pandoc/releases/download/'+$PandocVersion+'/pandoc-'+$PandocVersion+'-windows-x86_64.zip') -OutFile $Zip
}
$Tmp=Join-Path $env:TEMP 'docforge-pandoc-unpacked'
if (Test-Path $Tmp) { Remove-Item -LiteralPath $Tmp -Recurse -Force }
Expand-Archive -LiteralPath $Zip -DestinationPath $Tmp -Force
$Pandoc=Get-ChildItem -Path $Tmp -Filter pandoc.exe -File -Recurse | Select-Object -First 1
if (-not $Pandoc) { throw 'Pandoc archive lacks pandoc.exe' }
$Bin=Join-Path $Dist 'tools\pandoc'
New-Item -ItemType Directory -Force -Path $Bin | Out-Null
Copy-Item -LiteralPath $Pandoc.FullName -Destination $Bin -Force
# Runtime smoke test: running a frozen version must not require installed Python.
Invoke-Checked -Executable (Join-Path $Dist 'DocForge.exe') -ArgumentList @('--version')
if (-not $Compiler) {
    $candidates=@(
      (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 7\ISCC.exe'),
      (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
      (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe')
    )
    $Compiler=$candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $Compiler -or -not (Test-Path -LiteralPath $Compiler)) {
    throw 'Inno Setup compiler ISCC.exe not found. Install Inno Setup 6/7 on the Windows build machine.'
}
Invoke-Checked -Executable $Compiler -ArgumentList @('windows\inno\DocForge.iss')
Get-ChildItem -LiteralPath (Join-Path $Root 'dist\installer') -Filter '*.exe' | Select-Object FullName,Length
