@echo off
setlocal
cd /d "%~dp0.."
echo === V44 Web App Diagnostics ===
echo.
where py 2>nul && py --version || echo ERROR: py not found
where node 2>nul && node --version || echo ERROR: node not found
where npm 2>nul && npm --version || echo ERROR: npm not found
echo.
echo Listening ports:
netstat -ano | findstr ":8001\|:5175"
echo.
if exist "webapp\frontend\node_modules\.bin\vite.cmd" (
  echo Vite dependency: PRESENT
) else (
  echo Vite dependency: MISSING - run START_WEBAPP.cmd once with internet access
)
echo.
echo Port 5175 owner details:
powershell -NoProfile -Command "$c=Get-NetTCPConnection -State Listen -LocalPort 5175 -ErrorAction SilentlyContinue; if(-not $c){'5175: FREE'} else {$c | ForEach-Object {$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$_.OwningProcess); '5175 PID '+$_.OwningProcess+' : '+$p.CommandLine}}"
echo.
py -c "from webapp.backend.main import app; print('Backend import: OK')" 2>nul || python -c "from webapp.backend.main import app; print('Backend import: OK')" 2>nul || echo Backend import: FAILED
pause
endlocal
