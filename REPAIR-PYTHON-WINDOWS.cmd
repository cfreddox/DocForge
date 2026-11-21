@echo off
setlocal
if not exist "%~dp0windows\repair-python.ps1" (
  echo Missing windows\repair-python.ps1. Extract entire archive.
  pause
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\repair-python.ps1"
set "RESULT=%errorlevel%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%
