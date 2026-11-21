@echo off
setlocal
set "DOCFORGE=%LOCALAPPDATA%\DocForge"
set "PY=%DOCFORGE%\venv313\Scripts\python.exe"
if not exist "%PY%" (
  echo DocForge runtime not found: "%PY%"
  pause
  exit /b 1
)
if not exist "%DOCFORGE%\healthcheck.py" (
  echo Smoke test not found: "%DOCFORGE%\healthcheck.py"
  pause
  exit /b 1
)
"%PY%" "%DOCFORGE%\healthcheck.py"
if errorlevel 1 goto smoke_failed
echo.
echo DocForge smoke test PASSED.
echo Opening the DocForge main window...
"%PY%" "%DOCFORGE%\launcher.py" gui
if errorlevel 1 goto launch_failed
pause
exit /b 0
:smoke_failed
echo.
echo Smoke test FAILED, see the output above.
pause
exit /b 1
:launch_failed
echo.
echo DocForge did not launch. Check "%DOCFORGE%\logs\last-launch.log"
pause
exit /b 1
