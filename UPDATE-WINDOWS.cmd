@echo off
setlocal
rem Same entry point as installation: auto-detect existing DocForge.
call "%~dp0INSTALL-WINDOWS.cmd"
exit /b %errorlevel%
