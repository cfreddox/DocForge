@echo off
setlocal
if not exist "%~dp0windows\START-HERE.cmd" (
  echo Incomplete DocForge package. Extract all files first.
  pause
  exit /b 2
)
call "%~dp0windows\START-HERE.cmd"
exit /b %errorlevel%
