@echo off
setlocal
cd /d "%~dp0"
start "Career Agent Desktop" pythonw.exe "%~dp0desktop_launcher.pyw"
endlocal
