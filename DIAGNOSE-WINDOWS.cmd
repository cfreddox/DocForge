@echo off
setlocal
if not exist "%~dp0windows\diagnose-python.ps1" (
  echo Extract the whole DocForge ZIP before running this diagnostic.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\diagnose-python.ps1" -Show
set "CODE=%errorlevel%"
echo.
echo Report: %%LOCALAPPDATA%%\DocForge-InstallCache\python-diagnostics.txt
echo Please send this report for diagnosis. It does not modify installed Python.
pause
exit /b %CODE%
