@echo off
setlocal
chcp 65001 >nul
set "APP=%LOCALAPPDATA%\DocForge"
set "PY=%APP%\venv313\Scripts\python.exe"
if not exist "%PY%" (
 echo Python environment not found. Run START-HERE.cmd first.
 pause
 exit /b 1
)
echo [DocForge] Running GUI with diagnostics. Please keep this window open.
"%PY%" "%APP%\launcher.py" gui
set "RESULT=%errorlevel%"
echo.
if not "%RESULT%"=="0" (
 echo [DocForge] Startup error: %RESULT%
 echo Log: "%APP%\logs\last-launch.log"
 if exist "%APP%\logs\last-launch.log" type "%APP%\logs\last-launch.log"
) else (
 echo [DocForge] The application exited normally.
)
echo.
pause
exit /b %RESULT%
