@echo off
setlocal
cd /d "%~dp0"
call "%~dp0webapp\START_WEBAPP.cmd"
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
