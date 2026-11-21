@echo off
setlocal
if not exist "%~dp0install.ps1" (
  echo Required install.ps1 missing. Extract the entire release archive.
  pause
  exit /b 1
)
if exist "%~dp0Setup-DocForge.ps1" (
  powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0Setup-DocForge.ps1"
  set "STATUS=%errorlevel%"
  if not "%STATUS%"=="90" exit /b %STATUS%
)
echo The graphical setup is not available; switching to the console installer.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
set "STATUS=%errorlevel%"
if not "%STATUS%"=="0" pause
exit /b %STATUS%
