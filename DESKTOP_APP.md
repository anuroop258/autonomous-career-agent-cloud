# Desktop Application Mode

This package keeps the existing v28 job-automation logic unchanged and adds a Windows desktop launcher.

## One-click run (no terminal windows)

Double-click:

`START_DESKTOP.cmd`

The launcher starts the existing FastAPI backend and Vite frontend without opening separate terminal windows, waits for `127.0.0.1:8001` and `localhost:5175`, then opens the existing Career Agent dashboard in your browser.

The desktop window also has direct buttons for Naukri, Indeed, LinkedIn, and Stop Automation. These call the same existing backend API used by the web dashboard; the underlying platform agents are not replaced.

## Build a real EXE on Windows

Double-click:

`BUILD_DESKTOP_APP.cmd`

It installs PyInstaller (when needed) and produces:

`dist\\CareerAgentDesktop\\CareerAgentDesktop.exe`

Keep the generated EXE inside the project folder (or a child folder) so it can locate `webapp\\backend\\main.py`.

## What changed

Only desktop-startup files were added:

- `desktop_launcher.pyw`
- `START_DESKTOP.cmd`
- `BUILD_DESKTOP_APP.cmd`
- `DESKTOP_APP.md`

Existing Naukri / Indeed / LinkedIn automation flows, resume routing, form filling, and database logic were not rewritten for this desktop wrapper.
