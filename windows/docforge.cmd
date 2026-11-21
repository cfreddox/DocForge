@echo off
setlocal
"%~dp0venv313\Scripts\python.exe" "%~dp0launcher.py" %*
exit /b %errorlevel%
