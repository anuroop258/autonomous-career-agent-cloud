@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo Building Career Agent Desktop application
echo ============================================
py -3 -m pip install --upgrade pyinstaller
if errorlevel 1 (
  echo Failed to install PyInstaller.
  pause
  exit /b 1
)
py -3 -m PyInstaller --noconfirm --clean --onedir --windowed --name CareerAgentDesktop desktop_launcher.pyw
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)
echo.
echo Build complete:
echo   %~dp0dist\CareerAgentDesktop\CareerAgentDesktop.exe
echo.
echo Keep this EXE inside the v28_current project folder or a child folder so it can find webapp/backend/main.py.
pause
