@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run scripts\setup.ps1 first.
  pause
  exit /b 1
)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "TEMP=%CD%\.cache\tmp"
set "TMP=%TEMP%"
set "PYTHONPYCACHEPREFIX=%CD%\.cache\pycache"
".venv\Scripts\python.exe" -m app.reset
if errorlevel 1 pause
