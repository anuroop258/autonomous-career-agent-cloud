@echo off
setlocal
cd /d "%~dp0"
echo ==============================================
echo JOB AGENT - FIRST TIME SETUP
 echo ==============================================
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Dependency installation failed.
  pause
  exit /b 1
)
echo.
echo Setup complete.
echo Playwright Python package is installed.
echo This project uses your existing Chrome through CDP, so no Playwright browser download is required.
pause
