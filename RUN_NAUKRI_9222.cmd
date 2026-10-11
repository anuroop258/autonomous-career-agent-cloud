@echo off
cd /d "%~dp0"
echo Starting Naukri on CDP port 9222...
powershell -NoProfile -ExecutionPolicy Bypass -Command "& 'C:\Program Files\Google\Chrome\Application\chrome.exe' --remote-debugging-port=9222 --user-data-dir='$env:LOCALAPPDATA\NaukriAgentRealChrome' --profile-directory='Default'"
py main.py naukri
pause
