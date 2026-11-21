# Optional developer-only build. Run on a Windows machine AFTER START-HERE.cmd.
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$App = Join-Path $env:LOCALAPPDATA 'DocForge'
$Python = Join-Path $App 'venv313\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw 'DocForge must be installed with START-HERE.cmd before building an EXE.'
}
Set-Location $Root
& $Python -m pip install --disable-pip-version-check pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Unable to install PyInstaller.' }
& $Python -m PyInstaller --noconfirm --clean --onedir --windowed --name DocForge --paths . `
    --collect-all fitz --collect-all PIL --collect-all PySide6 --collect-all office2pdf `
    --hidden-import=docforge.pdf_editor --hidden-import=docforge.word_workflow `
    --hidden-import=docforge.word_ui --hidden-import=docforge.quick_actions `
    --hidden-import=docforge.windows_tray --hidden-import=docforge.md_assets `
    --collect-all tkinterdnd2 --add-data 'assets;assets' 'windows\launcher.py'
if ($LASTEXITCODE -ne 0) { throw 'Windows EXE build failed.' }
Write-Host 'Built a developer EXE in dist\DocForge. Pandoc remains an app-local executable; office2pdf is bundled with the EXE.'
