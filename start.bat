@echo off
title Shorts Studio
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Get it from https://www.python.org/downloads/
  echo During install, tick "Add Python to PATH". Then double-click start.bat again.
  pause
  exit /b
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: setting things up. This takes a few minutes, only once.
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

start "" http://127.0.0.1:5000
".venv\Scripts\python.exe" app.py
pause
