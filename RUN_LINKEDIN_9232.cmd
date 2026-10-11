@echo off
cd /d "%~dp0"
echo Starting LinkedIn on CDP port 9232...
powershell -NoProfile -ExecutionPolicy Bypass -Command "& 'C:\Program Files\Google\Chrome\Application\chrome.exe' --remote-debugging-port=9232 --user-data-dir='$env:LOCALAPPDATA\LinkedInAgentRealChrome' --profile-directory='Default'"
py main.py linkedin
pause
