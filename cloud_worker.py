"""Dedicated Render background worker for the Autonomous Career Agent."""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from cloud_queue import (
    ROOT, active_tasks, acquire_shared_mutation_lock, claim_next_task, ensure_schema, get_service_state,
    initialize_shared_snapshot, list_browser_sessions, push_shared_snapshot, release_shared_mutation_lock,
    recover_stale_tasks, set_service_state, sync_shared_from_store, task_control, update_task,
)

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
PROFILE_DIR = DATA_DIR / "browser_profiles"
SESSION_DIR = DATA_DIR / "browser_sessions"
RUNTIME = ROOT / "webapp" / "runtime"
PORTS = {"naukri": 9222, "indeed": 9222, "shine": 9222, "timesjobs": 9222, "glassdoor": 9222, "linkedin": 9232}
PORTAL_URLS = {
    "naukri": "https://www.naukri.com/", "indeed": "https://www.indeed.com/",
    "linkedin": "https://www.linkedin.com/feed/", "shine": "https://www.shine.com/",
    "timesjobs": "https://www.timesjobs.com/", "glassdoor": "https://www.glassdoor.co.in/Job/index.htm",
}
STOP = threading.Event()
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
CHROME_PROCESSES: dict[int, subprocess.Popen] = {}
SESSION_STAMPS: dict[str, str] = {}


def _cdp_open(port: int) -> bool:
    import socket as _socket
    try:
        with _socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _chrome_path() -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        executable = p.chromium.executable_path
    if not executable or not Path(executable).is_file():
        raise RuntimeError("Playwright Chromium executable is missing in the worker image")
    return executable


def _launch_browser(port: int, profile_path: Path, start_url: str) -> None:
    if _cdp_open(port):
        return
    profile_path.mkdir(parents=True, exist_ok=True)
    chrome = _chrome_path()
    args = [
        chrome, f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile_path}", "--profile-directory=Default", "--headless=new",
        "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--disable-background-networking",
    ]
    proc = subprocess.Popen(args + [start_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           start_new_session=(os.name != "nt"))
    CHROME_PROCESSES[port] = proc
    deadline = time.time() + 25
    while time.time() < deadline and not _cdp_open(port):
        if proc.poll() is not None:
            raise RuntimeError(f"Chromium exited early for CDP port {port} (code {proc.returncode})")
        time.sleep(0.25)
    if not _cdp_open(port):
        raise RuntimeError(f"Chromium did not open CDP port {port} within 25 seconds")


def _apply_storage_state(portal: str, state: dict[str, Any]) -> bool:
    port = PORTS[portal]
    if not _cdp_open(port):
        return False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=8000)
            contexts = browser.contexts
            if not contexts:
                browser.close()
                return False
            context = contexts[0]
            cookies = state.get("cookies", [])
            if cookies:
                context.add_cookies(cookies)
            for item in state.get("origins", []):
                origin = str(item.get("origin", ""))
                if not origin.startswith("https://"):
                    continue
                page = context.new_page()
                try:
                    page.goto(origin, wait_until="domcontentloaded", timeout=10000)
                    entries = item.get("localStorage", [])
                    page.evaluate("entries => { for (const e of entries) localStorage.setItem(e.name, e.value); }", entries)
                except Exception:
                    pass
                finally:
                    page.close()
            browser.close()
        return True
    except Exception as exc:
        # Do not dump cookie values or serialized session payloads into logs.
        print(f"[worker-session] failed to apply session for {portal}: {type(exc).__name__}: {exc}", flush=True)
        return False


def _refresh_sessions() -> None:
    for item in list_browser_sessions():
        portal = item["portal"]
        stamp_obj = item.get("updated_at")
        stamp = stamp_obj.isoformat() if hasattr(stamp_obj, "isoformat") else str(stamp_obj)
        if SESSION_STAMPS.get(portal) == stamp:
            continue
        state = item.get("storage_state") or {}
        if _apply_storage_state(portal, state):
            SESSION_STAMPS[portal] = stamp


def _publish_worker_state() -> None:
    active = active_tasks()
    set_service_state("worker", {
        "worker_id": WORKER_ID,
        "pid": os.getpid(),
        "service": "career-worker",
        "cdp": {str(port): _cdp_open(port) for port in (9222, 9232)},
        "active_tasks": [{"task_id": t["task_id"], "portal": t["portal"], "status": t["status"], "child_pid": t.get("child_pid")} for t in active],
    })


def _terminate(proc: subprocess.Popen, timeout: float = 8.0) -> int | None:
    if proc.poll() is not None:
        return proc.returncode
    try:
        if os.name != "nt":
            import signal as _signal
            os.killpg(os.getpgid(proc.pid), _signal.SIGTERM)
        else:
            proc.terminate()
    except (OSError, ProcessLookupError):
        pass
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if os.name != "nt":
                import signal as _signal
                os.killpg(os.getpgid(proc.pid), _signal.SIGKILL)
            else:
                proc.kill()
        except (OSError, ProcessLookupError):
            pass
        try:
            return proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            return proc.returncode


def _execute_task(task: dict[str, Any]) -> None:
    portal = task["portal"]
    task_id = task["task_id"]
    log_path = RUNTIME / f"run_{portal}_{task_id}.log"
    RUNTIME.mkdir(parents=True, exist_ok=True)
    started = time.time()
    proc = None
    tail = ""
    final_rc = None
    final_status = "failed"
    final_error = None

    try:
        # The API publishes any recent changes before a task can be claimed. Pulling
        # again also makes worker restarts use the last durable snapshot.
        sync_shared_from_store(force=True)
        _refresh_sessions()
        if portal == "indeed":
            for name in ("indeed_human_verification.json", "indeed_human_verification.signal"):
                try:
                    (RUNTIME / name).unlink()
                except FileNotFoundError:
                    pass

        env = os.environ.copy()
        env["JOB_AGENT_PLATFORM"] = portal
        env["JOB_AGENT_CDP_PORT"] = str(PORTS[portal])
        if portal in {"indeed", "glassdoor"}:
            prefix = "indeed" if portal == "indeed" else "glassdoor"
            env["JOB_AGENT_HUMAN_VERIFICATION_MARKER"] = str(RUNTIME / f"{prefix}_human_verification.json")
            env["JOB_AGENT_HUMAN_VERIFICATION_SIGNAL"] = str(RUNTIME / f"{prefix}_human_verification.signal")

        with log_path.open("a", encoding="utf-8", buffering=1) as handle:
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / "main.py"), portal], cwd=str(ROOT), env=env,
                stdout=handle, stderr=subprocess.STDOUT, text=True,
                start_new_session=(os.name != "nt"),
            )
            update_task(task_id, child_pid=proc.pid, heartbeat_at="NOW()")
            last_snapshot = 0.0
            while proc.poll() is None and not STOP.is_set():
                ctrl = task_control(task_id) or {}
                if ctrl.get("continue_requested"):
                    signal_file = RUNTIME / ("indeed_human_verification.signal" if portal == "indeed" else f"{portal}_human_verification.signal")
                    signal_file.touch(exist_ok=True)
                    update_task(task_id, continue_requested=False)
                marker = RUNTIME / ("indeed_human_verification.json" if portal == "indeed" else f"{portal}_human_verification.json")
                tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-300:])[-45000:]
                if ctrl.get("cancel_requested"):
                    _terminate(proc)
                    break
                update_task(task_id, human_verification=marker.exists(), log_tail=tail, heartbeat_at="NOW()")
                now = time.time()
                if now - last_snapshot >= 12:
                    try:
                        push_shared_snapshot(include_files=False)
                        last_snapshot = now
                    except Exception as exc:
                        print(f"[worker-snapshot] interim publish failed: {type(exc).__name__}: {exc}", flush=True)
                try:
                    _publish_worker_state()
                except Exception:
                    pass
                time.sleep(2.5)
            if STOP.is_set() and proc.poll() is None:
                _terminate(proc)
            final_rc = proc.poll()

        ctrl = task_control(task_id) or {}
        if ctrl.get("cancel_requested") or STOP.is_set():
            final_status = "cancelled"
        elif final_rc == 0:
            final_status = "completed"
        else:
            final_status = "failed"
            final_error = f"Agent process exited with code {final_rc}"
    except Exception as exc:
        if proc and proc.poll() is None:
            _terminate(proc)
        final_rc = proc.returncode if proc else None
        final_status = "failed"
        final_error = f"{type(exc).__name__}: {exc}"
        print(f"[worker] task={task_id} failed: {final_error}", flush=True)
    finally:
        try:
            if log_path.exists():
                tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-300:])[-45000:]
        except OSError:
            pass
        # Keep the task active until the final full snapshot and terminal status are
        # committed under the same distributed lock. API writes then see the newest
        # snapshot once the lock is released.
        guard = None
        try:
            guard = acquire_shared_mutation_lock()
            try:
                push_shared_snapshot()
            except Exception as exc:
                message = f"Final shared-state snapshot failed: {type(exc).__name__}: {exc}. This run may have applied jobs; do not retry blindly."
                final_error = f"{final_error}; {message}" if final_error else message
                final_status = "failed"
            update_task(task_id, status=final_status, returncode=final_rc, finished_at="NOW()",
                        log_tail=tail, human_verification=False, error=final_error)
        except Exception as exc:
            # Leave the task as running if PostgreSQL itself cannot commit final state;
            # lease recovery will mark it failed later rather than report success.
            print(f"[worker] could not finalize task={task_id}: {type(exc).__name__}: {exc}", flush=True)
        finally:
            if guard is not None:
                release_shared_mutation_lock(guard)
        print(f"[worker] task={task_id} portal={portal} elapsed={time.time()-started:.1f}s status={final_status}", flush=True)


def _stop_handler(_signum, _frame):
    STOP.set()


def main() -> int:
    ensure_schema()
    recovered = recover_stale_tasks()
    if recovered:
        print(f"[worker] marked {recovered} stale task(s) failed; not auto-retrying to avoid duplicate submissions", flush=True)
    initialize_shared_snapshot()
    sync_shared_from_store(force=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _stop_handler)

    # Start both Chromium processes once. Portal groups share CDP port 9222, while
    # LinkedIn has its own persistent profile and port 9232 as in local mode.
    try:
        _launch_browser(9222, PROFILE_DIR / "shared-9222", PORTAL_URLS["naukri"])
        _launch_browser(9232, PROFILE_DIR / "linkedin", PORTAL_URLS["linkedin"])
    except Exception as exc:
        set_service_state("worker", {"worker_id": WORKER_ID, "error": f"browser startup: {type(exc).__name__}: {exc}", "cdp": {"9222": False, "9232": False}})
        print(f"[worker] browser startup failed: {type(exc).__name__}: {exc}", flush=True)
        return 2

    try:
        _refresh_sessions()
    except Exception as exc:
        message = f"session restore: {type(exc).__name__}: {exc}"
        set_service_state("worker", {"worker_id": WORKER_ID, "error": message,
                                        "cdp": {"9222": _cdp_open(9222), "9232": _cdp_open(9232)}})
        print(f"[worker] startup blocked: {message}", flush=True)
        for proc in CHROME_PROCESSES.values():
            if proc.poll() is None:
                _terminate(proc, timeout=3)
        return 3
    print(f"[worker] ready id={WORKER_ID}; polling PostgreSQL queue", flush=True)
    last_heartbeat = 0.0
    last_recovery = time.time()
    while not STOP.is_set():
        now = time.time()
        try:
            if now - last_heartbeat >= 10:
                _publish_worker_state()
                _refresh_sessions()
                last_heartbeat = now
            if now - last_recovery >= 60:
                recover_stale_tasks()
                last_recovery = now
            task = claim_next_task(WORKER_ID)
            if task:
                print(f"[worker] claimed task={task['task_id']} portal={task['portal']}", flush=True)
                _execute_task(task)
                continue
        except Exception as exc:
            print(f"[worker] loop error: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(5)
        time.sleep(1.5)

    for proc in CHROME_PROCESSES.values():
        if proc.poll() is None:
            _terminate(proc, timeout=3)
    try:
        set_service_state("worker", {"worker_id": WORKER_ID, "stopped": True, "cdp": {"9222": False, "9232": False}})
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
