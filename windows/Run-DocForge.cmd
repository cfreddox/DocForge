@echo off
if not exist "%LOCALAPPDATA%\DocForge\docforge.cmd" (
  echo DocForge is not installed. Run START-HERE.cmd first.
  pause
  exit /b 1
)
call "%LOCALAPPDATA%\DocForge\docforge.cmd" gui
