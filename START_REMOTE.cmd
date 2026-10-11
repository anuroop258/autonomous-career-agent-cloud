@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PROJECT_ROOT=%CD%"
set "KEYFILE=%PROJECT_ROOT%\webapp\runtime\remote_api_key.txt"

echo ============================================
echo Career Agent - REMOTE ACCESS (key protected)
echo ============================================
echo.

where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python not found. Install Python and add it to PATH.
    pause
    exit /b 1
  ) else (
    set "PYTHON_CMD=python"
  )
) else (
  set "PYTHON_CMD=py"
)

rem Build the web page once so the backend can serve it (needs Node.js only for this step).
if not exist "%PROJECT_ROOT%\webapp\frontend\dist\index.html" (
  where npm >nul 2>nul
  if errorlevel 1 (
    echo ERROR: The web page is not built and npm was not found. Install Node.js and run again.
    pause
    exit /b 1
  )
  pushd "%PROJECT_ROOT%\webapp\frontend"
  call npm ci --no-audit --no-fund
  call npm run build
  popd
)

rem Create a long random access key the first time. Delete the file to rotate the key.
if not exist "%KEYFILE%" (
  powershell -NoProfile -Command "([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')) | Set-Content -NoNewline -Path '%KEYFILE%'"
)
set /p CAREER_AGENT_API_KEY=<"%KEYFILE%"

rem Stop an older copy of the backend on port 8001.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Get-NetTCPConnection -State Listen -LocalPort 8001 -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$_) -ErrorAction SilentlyContinue; if($p -and [string]$p.CommandLine -match 'uvicorn.*webapp') { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } } } catch {}"

echo Starting the backend (it only listens on this PC: 127.0.0.1:8001)...
start "Career Agent API (remote)" cmd /k "cd /d "%PROJECT_ROOT%" && %PYTHON_CMD% -m uvicorn webapp.backend.main:app --host 127.0.0.1 --port 8001"
timeout /t 3 /nobreak >nul

echo.
echo ACCESS KEY (type this on your phone/laptop login screen):
echo.
echo     %CAREER_AGENT_API_KEY%
echo.
echo Saved in: %KEYFILE%
echo Local test: http://127.0.0.1:8001
echo.

where cloudflared >nul 2>nul
if errorlevel 1 (
  echo Cloudflare Tunnel is not installed, so the page is NOT on the internet yet.
  echo Install it with:   winget install Cloudflare.cloudflared
  echo Then run this file again. See REMOTE_ACCESS.md for the other option (Tailscale).
) else (
  echo Starting the tunnel. Open the https://....trycloudflare.com address it prints.
  start "Cloudflare Tunnel" cmd /k "cloudflared tunnel --url http://127.0.0.1:8001"
)
echo.
pause
endlocal
