@echo off
setlocal
cd /d "%~dp0..\webapp\frontend"
where node >nul 2>nul
if errorlevel 1 (
  echo ERROR: Node.js not found.
  exit /b 1
)
node free-port.mjs 5175
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
