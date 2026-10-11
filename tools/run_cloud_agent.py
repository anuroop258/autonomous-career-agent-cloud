"""Run one existing portal agent, stream logs to the Cloudflare control API, and honor stop requests."""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALID_PORTALS = {"naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"}


def api_request(path: str, method: str = "GET", payload: dict | None = None, timeout: int = 8):
    base = os.getenv("CLOUD_CONTROL_API_BASE", "").rstrip("/")
    key = os.getenv("CLOUD_CONTROL_API_KEY", "")
    if not base or not key:
        raise RuntimeError("CLOUD_CONTROL_API_BASE and CLOUD_CONTROL_API_KEY must be configured")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base + path, data=body, method=method, headers={
        "Content-Type": "application/json", "X-API-Key": key, "User-Agent": "career-agent-github-runner",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def report(status: str, task_id: str, lines: deque[str], **extra):
    payload = {
        "task_id": task_id,
        "status": status,
        "log_tail": "".join(lines)[-14000:],
        "github_run_id": os.getenv("GITHUB_RUN_ID"),
        **extra,
    }
    try:
        api_request("/api/worker/report", "POST", payload)
    except Exception as exc:
        print(f"WARNING: could not report status to control API ({type(exc).__name__}).")


def stop_requested(task_id: str) -> bool:
    try:
        response = api_request("/api/worker/control?task_id=" + urllib.parse.quote(task_id), "GET")
        return bool(response.get("stop_requested"))
    except Exception as exc:
        print(f"WARNING: could not check stop request ({type(exc).__name__}); continuing current run.")
        return False


def terminate_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try: proc.terminate()
        except OSError: pass
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try: proc.kill()
            except OSError: pass
        try: proc.wait(timeout=3)
        except subprocess.TimeoutExpired: pass


def main() -> int:
    portal = os.getenv("CAREER_AGENT_PORTAL", "").strip().lower()
    task_id = os.getenv("CAREER_AGENT_TASK_ID", "").strip()
    max_jobs = os.getenv("CAREER_AGENT_MAX_JOBS", "1").strip()
    if portal not in VALID_PORTALS or not task_id:
        print("CAREER_AGENT_PORTAL and CAREER_AGENT_TASK_ID are required.", file=sys.stderr)
        return 2
    try: api_request("/api/health", "GET")  # health is public; used only to validate base URL
    except Exception:
        # /api/health does not require the API key but is not required for the run itself.
        pass
    lines: deque[str] = deque(maxlen=180)
    initial = f"Remote run starting: portal={portal}, max_jobs={max_jobs}, task_id={task_id}\n"
    lines.append(initial); print(initial, end="", flush=True)
    if stop_requested(task_id):
        report("cancelled", task_id, lines, exit_code=130, error="Stop requested before the agent started")
        print("Stop was already requested; agent not launched.")
        return 130
    env = os.environ.copy()
    env["JOB_AGENT_PLATFORM"] = portal
    env["CAREER_AGENT_CLOUD_RUN"] = "1"
    env["MAX_APPLICATIONS"] = max_jobs
    command = [sys.executable, str(ROOT / "main.py"), portal]
    print("Command: python main.py " + portal, flush=True)
    try:
        proc = subprocess.Popen(
            command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, start_new_session=True,
        )
    except Exception as exc:
        lines.append(f"Failed to launch agent: {exc}\n")
        report("failed", task_id, lines, error=f"Failed to launch agent: {type(exc).__name__}")
        return 1

    output_queue: queue.Queue[str | None] = queue.Queue()
    def reader():
        try:
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, ""):
                output_queue.put(line)
        finally:
            output_queue.put(None)
    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    last_report = 0.0
    last_control = 0.0
    stop = False
    stream_ended = False
    while not stream_ended or proc.poll() is None:
        now = time.monotonic()
        try:
            line = output_queue.get(timeout=0.4)
            if line is None:
                stream_ended = True
            else:
                print(line, end="", flush=True)
                lines.append(line)
        except queue.Empty:
            pass
        now = time.monotonic()
        if now - last_control >= 5:
            last_control = now
            if stop_requested(task_id):
                stop = True
                lines.append("\nSTOP requested from control page. Terminating the agent process.\n")
                print("STOP requested from control page. Terminating the agent process.", flush=True)
                terminate_process(proc)
                break
        if now - last_report >= 12:
            last_report = now
            report("running", task_id, lines)
    if proc.poll() is None:
        terminate_process(proc)
    return_code = proc.returncode if proc.returncode is not None else 1
    if stop or return_code in (-signal.SIGTERM, -signal.SIGKILL, 130):
        report("cancelled", task_id, lines, exit_code=130, error="Run was stopped from the control page")
        return 130
    if return_code == 0:
        report("completed", task_id, lines, exit_code=0)
        return 0
    report("failed", task_id, lines, exit_code=return_code, error=f"Agent exited with code {return_code}")
    return return_code

if __name__ == "__main__":
    raise SystemExit(main())
