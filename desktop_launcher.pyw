import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

APP_TITLE = "Career Agent Desktop"
HOST = "127.0.0.1"
BACKEND_PORT = 8001
FRONTEND_PORT = 5175
DASHBOARD_URL = f"http://{HOST}:{FRONTEND_PORT}"


def project_root() -> Path:
    """Resolve the actual project root for .pyw and PyInstaller builds."""
    # Normal source run: this file lives at <project>/desktop_launcher.pyw
    here = Path(__file__).resolve().parent
    if (here / "webapp" / "backend" / "main.py").exists():
        return here

    # PyInstaller onedir build: <project>/desktop_app/CareerAgentDesktop.exe
    exe_dir = Path(sys.executable).resolve().parent
    candidates = [exe_dir, exe_dir.parent, exe_dir.parent.parent]
    for p in candidates:
        if (p / "webapp" / "backend" / "main.py").exists():
            return p
    raise RuntimeError("Could not locate v28_current project root.")


def python_command():
    # The desktop launcher may itself be an .exe, so never use sys.executable
    # as the backend interpreter when frozen.
    if not getattr(sys, "frozen", False):
        return [sys.executable]
    py = shutil.which("py")
    if py:
        return [py]
    python = shutil.which("python") or shutil.which("python3")
    if python:
        return [python]
    raise RuntimeError("Python launcher not found. Install Python and ensure 'py' is on PATH.")


def npm_command():
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm:
        return npm
    raise RuntimeError("npm was not found. Install Node.js and ensure npm is on PATH.")


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.35)
        try:
            s.connect((HOST, port))
            return True
        except OSError:
            return False


def http_json(method: str, url: str, payload=None, timeout=8):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw else {}


def http_ready(url: str, timeout=2):
    """Return True only when an HTTP service is actually responding."""
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except (URLError, HTTPError, OSError):
        return False


def services_ready() -> bool:
    """Require both backend health and a serving frontend before opening the UI."""
    if not port_open(BACKEND_PORT) or not port_open(FRONTEND_PORT):
        return False
    try:
        health = http_json("GET", f"http://{HOST}:{BACKEND_PORT}/api/health", timeout=2)
        if not health.get("ok"):
            return False
    except Exception:
        return False
    return http_ready(DASHBOARD_URL, timeout=2)


def wait_for_services(timeout_seconds=120, poll_seconds=0.5) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if services_ready():
            return True
        time.sleep(poll_seconds)
    return False


class DesktopApp:
    def __init__(self, root_tk: tk.Tk):
        self.ui = root_tk
        self.ui.title(APP_TITLE)
        self.ui.geometry("760x560")
        self.ui.minsize(680, 500)
        self.ui.protocol("WM_DELETE_WINDOW", self.close)

        self.project = project_root()
        self.processes = {}
        self.log_queue = queue.Queue()
        self.closed = False
        self.services_ready = False

        self.status_var = tk.StringVar(value="Starting…")
        self.cdp_var = tk.StringVar(value="CDP 9222: —   LinkedIn 9232: —")

        self._build_ui()
        self._set_controls_ready(False)
        self._append("Project: " + str(self.project))
        self._append("Starting backend and frontend without opening terminal windows…")
        threading.Thread(target=self._start_services, daemon=True).start()
        self.ui.after(150, self._drain_logs)
        self.ui.after(1200, self._refresh_status)

    def _build_ui(self):
        outer = tk.Frame(self.ui, bg="#0b1220")
        outer.pack(fill="both", expand=True)

        title = tk.Label(outer, text="Career Agent", font=("Segoe UI", 22, "bold"), fg="white", bg="#0b1220")
        title.pack(anchor="w", padx=24, pady=(20, 2))
        subtitle = tk.Label(outer, text="Desktop control panel for the existing v28 project", font=("Segoe UI", 10), fg="#94a3b8", bg="#0b1220")
        subtitle.pack(anchor="w", padx=24, pady=(0, 14))

        top = tk.Frame(outer, bg="#111827", highlightbackground="#263244", highlightthickness=1)
        top.pack(fill="x", padx=24, pady=(0, 12))
        tk.Label(top, text="Status", fg="#94a3b8", bg="#111827", font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 2))
        tk.Label(top, textvariable=self.status_var, fg="#e2e8f0", bg="#111827", font=("Segoe UI", 11, "bold")).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 12))
        tk.Label(top, textvariable=self.cdp_var, fg="#94a3b8", bg="#111827", font=("Segoe UI", 9)).grid(row=0, column=1, rowspan=2, sticky="e", padx=14)
        top.grid_columnconfigure(1, weight=1)

        actions = tk.Frame(outer, bg="#0b1220")
        actions.pack(fill="x", padx=24)
        self.buttons = {}
        specs = [
            ("Dashboard", self.open_dashboard, "#4f46e5"),
            ("Naukri", lambda: self.run_portal("naukri"), "#334155"),
            ("Indeed", lambda: self.run_portal("indeed"), "#334155"),
            ("LinkedIn", lambda: self.run_portal("linkedin"), "#334155"),
            ("Shine", lambda: self.run_portal("shine"), "#334155"),
            ("TimesJobs", lambda: self.run_portal("timesjobs"), "#334155"),
            ("Glassdoor", lambda: self.run_portal("glassdoor"), "#334155"),
            ("Stop Automation", self.stop_automation, "#7f1d1d"),
        ]
        for i, (label, command, bg) in enumerate(specs):
            btn = tk.Button(actions, text=label, command=command, bg=bg, fg="white", activebackground=bg,
                            activeforeground="white", relief="flat", bd=0, padx=14, pady=9, font=("Segoe UI", 10, "bold"),
                            cursor="hand2")
            btn.grid(row=i // 3, column=i % 3, padx=(0 if i % 3 == 0 else 8, 8), pady=5, sticky="ew")
            self.buttons[label] = btn
        for c in range(3):
            actions.grid_columnconfigure(c, weight=1)

        note = tk.Label(outer,
                        text="The existing browser automation code is unchanged. This launcher only hides the backend/frontend terminals, opens the existing dashboard, and exposes the same portal controls in one window.",
                        justify="left", wraplength=700, fg="#64748b", bg="#0b1220", font=("Segoe UI", 9))
        note.pack(anchor="w", padx=24, pady=(8, 10))

        log_frame = tk.Frame(outer, bg="#111827", highlightbackground="#263244", highlightthickness=1)
        log_frame.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        tk.Label(log_frame, text="Launcher log", fg="#cbd5e1", bg="#111827", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(9, 4))
        self.log = tk.Text(log_frame, bg="#020617", fg="#cbd5e1", insertbackground="white", relief="flat", height=14,
                           font=("Consolas", 9), wrap="word")
        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log.configure(state="disabled")

    def _set_controls_ready(self, ready: bool):
        self.services_ready = ready
        state = "normal" if ready else "disabled"
        for button in self.buttons.values():
            button.configure(state=state)


    def _append(self, text: str):
        self.log_queue.put(text)

    def _drain_logs(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", line.rstrip() + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        if not self.closed:
            self.ui.after(150, self._drain_logs)

    def _free_stale_project_ports(self):
        """Free only stale V44 uvicorn/vite processes occupying our fixed ports."""
        if os.name != "nt":
            return
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if not ps:
            return
        script = r"""
$rules = @{ 8001 = 'uvicorn.*webapp[\\/]backend[\\/]main:app'; 5175 = 'vite' }
foreach ($port in $rules.Keys) {
  try {
    $owners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($owner in $owners) {
      if (-not $owner) { continue }
      $proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $owner) -ErrorAction SilentlyContinue
      if ($proc -and [string]$proc.CommandLine -match $rules[$port]) {
        Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
        Write-Output ("Stopped stale V44 process PID {0} on port {1}" -f $owner, $port)
      }
    }
  } catch {}
}
"""
        try:
            result = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                                    capture_output=True, text=True, timeout=15)
            for line in (result.stdout or "").splitlines():
                self._append(line)
        except Exception as exc:
            self._append("Port cleanup skipped: " + str(exc))

    def _start_services(self):
        try:
            self._free_stale_project_ports()
            py = python_command()
            backend_cmd = py + ["-m", "uvicorn", "webapp.backend.main:app", "--host", HOST, "--port", str(BACKEND_PORT)]
            self._spawn("backend", backend_cmd, self.project)
            self._append(f"Backend: http://{HOST}:{BACKEND_PORT}")

            frontend_dir = self.project / "webapp" / "frontend"
            npm = npm_command()
            vite_cmd = frontend_dir / "node_modules" / ".bin" / ("vite.cmd" if os.name == "nt" else "vite")
            if not vite_cmd.exists():
                self._append("Frontend dependencies are missing; running npm install once…")
                install = subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=str(frontend_dir), capture_output=True, text=True)
                if install.returncode != 0:
                    raise RuntimeError("npm install failed: " + (install.stderr or install.stdout)[-1200:])
                self._append("npm install completed.")

            frontend_cmd = [npm, "run", "dev", "--", "--host", HOST]
            self._spawn("frontend", frontend_cmd, frontend_dir)
            self._append(f"Frontend: {DASHBOARD_URL}")

            self._append("Waiting for backend health and the frontend HTTP server…")
            if wait_for_services(timeout_seconds=120, poll_seconds=0.5):
                self._append("Dashboard is ready.")
                self.ui.after(0, lambda: self._set_controls_ready(True))
                self.ui.after(0, lambda: self.status_var.set("Ready"))
                self.ui.after(0, self.open_dashboard)
                return
            raise RuntimeError("Timed out waiting for the dashboard services on ports 8001/5175.")
        except Exception as exc:
            self._append("ERROR: " + str(exc))
            self.ui.after(0, lambda: self.status_var.set("Startup failed"))
            self.ui.after(0, lambda: messagebox.showerror(APP_TITLE, str(exc)))

    def _spawn(self, key, cmd, cwd):
        log_dir = self.project / "webapp" / "runtime"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"desktop_{key}.log"
        fh = open(log_path, "a", encoding="utf-8", buffering=1)
        kwargs = {
            "cwd": str(cwd),
            "stdout": fh,
            "stderr": subprocess.STDOUT,
            "text": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(cmd, **kwargs)
        self.processes[key] = (proc, fh)
        self._append(f"Started {key} (PID {proc.pid}). Log: {log_path}")

    def open_dashboard(self):
        def work():
            if not self.services_ready:
                self._append("Dashboard requested before startup completed; waiting for services…")
                if not wait_for_services(timeout_seconds=120, poll_seconds=0.5):
                    self._append("Dashboard is still unavailable after waiting for startup.")
                    self.ui.after(0, lambda: messagebox.showerror(
                        APP_TITLE,
                        "The dashboard is not ready yet. Check the launcher log for the startup error."
                    ))
                    return
                self.ui.after(0, lambda: self._set_controls_ready(True))
            try:
                import webbrowser
                webbrowser.open(DASHBOARD_URL)
            except Exception as exc:
                self._append("Could not open dashboard: " + str(exc))
        threading.Thread(target=work, daemon=True).start()

    def _api_call(self, method, path, payload=None):
        return http_json(method, f"http://{HOST}:{BACKEND_PORT}{path}", payload)

    def run_portal(self, portal):
        def work():
            try:
                self._append(f"Launching {portal} Chrome/CDP…")
                self._api_call("POST", "/api/portal/launch", {"portal": portal})
                for _ in range(20):
                    try:
                        cdp = self._api_call("GET", "/api/cdp/status")
                        if cdp.get(portal, {}).get("connected"):
                            break
                    except Exception:
                        pass
                    time.sleep(0.6)
                else:
                    raise RuntimeError(f"{portal} Chrome/CDP did not become available.")
                self._api_call("POST", "/api/automation/start", {"portals": [portal]})
                self._append(f"{portal.title()} automation started.")
            except Exception as exc:
                self._append(f"{portal.title()} ERROR: {exc}")
                self.ui.after(0, lambda: messagebox.showerror(APP_TITLE, f"{portal.title()}: {exc}"))
        threading.Thread(target=work, daemon=True).start()

    def stop_automation(self):
        def work():
            try:
                self._api_call("POST", "/api/automation/stop")
                self._append("Automation stop requested.")
            except Exception as exc:
                self._append("Stop ERROR: " + str(exc))
        threading.Thread(target=work, daemon=True).start()

    def _refresh_status(self):
        if self.closed:
            return
        try:
            status = self._api_call("GET", "/api/automation/status", timeout=3)
            run_status = status.get("status", "idle")
            portals = ", ".join(status.get("portals", [])) or "none"
            self.status_var.set(f"Automation: {run_status} · running: {portals}")
        except Exception:
            pass
        try:
            cdp = self._api_call("GET", "/api/cdp/status", timeout=3)
            self.cdp_var.set(
                "CDP 9222: " + ("connected" if any(cdp.get(p, {}).get("connected") for p in ("naukri", "indeed", "shine", "timesjobs", "glassdoor")) else "—") +
                "   LinkedIn 9232: " + ("connected" if cdp.get("linkedin", {}).get("connected") else "—")
            )
        except Exception:
            pass
        self.ui.after(1200, self._refresh_status)

    def close(self):
        if self.closed:
            return
        self.closed = True
        # Stop only the hidden backend/frontend processes started by this desktop launcher.
        for key, (proc, fh) in list(self.processes.items()):
            try:
                if proc.poll() is None:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    else:
                        proc.terminate()
            except Exception:
                pass
            try:
                fh.close()
            except Exception:
                pass
        self.ui.destroy()


if __name__ == "__main__":
    app_root = tk.Tk()
    DesktopApp(app_root)
    app_root.mainloop()
