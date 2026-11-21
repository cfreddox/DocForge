@echo off
setlocal
chcp 65001 >nul
set "APP=%LOCALAPPDATA%\DocForge"
set "SRC=%~dp0..\docforge"
if not exist "%APP%\venv313\Scripts\python.exe" (
 echo DocForge runtime not found. Use START-HERE.cmd for initial installation.
 pause
 exit /b 1
)
if not exist "%SRC%\gui.py" (
 echo Missing application source. Extract the full archive first.
 pause
 exit /b 1
)
echo [DocForge] Closing application processes is recommended before repair.
if not exist "%APP%\docforge" mkdir "%APP%\docforge"
xcopy /E /I /Y /Q "%SRC%" "%APP%\docforge\" >nul
if errorlevel 1 goto :error
copy /Y "%~dp0launcher.py" "%APP%\launcher.py" >nul
if errorlevel 1 goto :error
copy /Y "%~dp0Diagnose-DocForge.cmd" "%APP%\Diagnose-DocForge.cmd" >nul
if errorlevel 1 goto :error
echo [DocForge] Application files repaired. Starting diagnostic launch.
call "%~dp0Diagnose-DocForge.cmd"
exit /b %errorlevel%
:error
echo [DocForge ERROR] Cannot update application files.
pause
exit /b 1
