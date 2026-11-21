@echo off
rem Windows launcher. All the logic lives in run.py so every platform behaves the same.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.9+ is required. Install it from https://www.python.org/ and try again.
  pause
  exit /b 1
)
python run.py %*
if errorlevel 1 pause
