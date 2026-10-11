@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."
set "PROJECT_ROOT=%CD%"
set "FRONTEND_DIR=%PROJECT_ROOT%\webapp\frontend"

echo ============================================
echo Job Agent V44 - Web App
echo ============================================
echo Backend : http://127.0.0.1:8001
echo Frontend: http://127.0.0.1:5175
echo.

rem Stop only stale V44 uvicorn/vite listeners from previous launches.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$targets=@{8001='uvicorn.*webapp[\\/]backend[\\/]main:app';5175='vite'}; foreach($port in $targets.Keys){ try { $pids=Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess -Unique; foreach($pid in $pids){ if(-not $pid){continue}; $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$pid) -ErrorAction SilentlyContinue; if($p -and [string]$p.CommandLine -match $targets[$port]){ Write-Host ('Stopping stale process PID '+$pid+' on port '+$port); Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue } } } catch {} }"

where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python launcher not found. Install Python and ensure py/python is on PATH.
    pause
    exit /b 1
  ) else (
    set "PYTHON_CMD=python"
  )
) else (
  set "PYTHON_CMD=py"
)

where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm not found. Install Node.js and ensure npm is on PATH.
  pause
  exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules\.bin\vite.cmd" (
  echo Frontend dependencies are missing. Installing once with package-lock.json...
  pushd "%FRONTEND_DIR%"
  call npm ci --no-audit --no-fund
  if errorlevel 1 (
    echo.
    echo ERROR: Frontend dependency installation failed.
    echo Check Node.js/npm, internet access, and the npm error above.
    popd
    pause
    exit /b 1
  )
  popd
) else (
  echo Frontend dependencies found - skipping npm install.
)

echo.
echo Releasing the reserved Vite port 5175...
pushd "%FRONTEND_DIR%"
call node free-port.mjs 5175
if errorlevel 1 (
  echo ERROR: Port 5175 is occupied by another process.
  popd
  pause
  exit /b 1
)
popd

echo.
echo Starting backend...
start "Job Agent V44 API" cmd /k "cd /d "%PROJECT_ROOT%" && %PYTHON_CMD% -m uvicorn webapp.backend.main:app --host 127.0.0.1 --port 8001"

timeout /t 2 /nobreak >nul

echo Starting frontend...
start "Job Agent V44 UI" cmd /k "cd /d "%FRONTEND_DIR%" && npm run dev -- --host 127.0.0.1 --port 5175 --strictPort"

echo.
echo Web app starting. Open http://127.0.0.1:5175 after Vite reports ready.
echo.
endlocal
