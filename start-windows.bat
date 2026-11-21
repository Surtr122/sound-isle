@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found.
  echo Install Python 3.10 or newer from https://www.python.org/downloads/
  echo During setup, enable "Add python.exe to PATH".
  pause
  exit /b 1
)
echo Starting Sound ^& Form...
python app.py
if errorlevel 1 (
  echo.
  echo The server stopped with an error. Check the message above.
  pause
)
