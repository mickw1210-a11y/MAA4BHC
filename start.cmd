@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" -TaskHome %*
set "startupExit=%ERRORLEVEL%"
if not "%startupExit%"=="0" pause
exit /b %startupExit%
