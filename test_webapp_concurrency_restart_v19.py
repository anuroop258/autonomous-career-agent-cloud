import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("backend_main_v19", ROOT / "webapp" / "backend" / "main.py")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

class FakeProc:
    _next = 1000
    def __init__(self):
        self.pid = FakeProc._next
        FakeProc._next += 1
        self.rc = None
    def poll(self):
        return self.rc
    def wait(self, timeout=None):
        return self.rc
    def terminate(self):
        self.rc = 0
    def kill(self):
        self.rc = -9

created = []
orig_popen = mod.subprocess.Popen
orig_port_open = mod._port_open

def fake_popen(*args, **kwargs):
    p = FakeProc(); created.append(p); return p

mod.subprocess.Popen = fake_popen
mod._port_open = lambda port: True

# reset state
mod.RUN_PROCESSES.clear(); mod.RUN_HANDLES.clear(); mod.RUN_STATE.update(status="idle", portals=[], pids={}, pid=None, runs={})

# Concurrent starts must be accepted for different portals.
r = mod.start_automation(mod.RunBody(portals=["linkedin", "indeed"]))
assert set(r["portals"]) == {"linkedin", "indeed"}, r
assert len(mod.RUN_PROCESSES) == 2, mod.RUN_PROCESSES

# Re-starting an already-running portal must not spawn a second process.
r2 = mod.start_automation(mod.RunBody(portals=["linkedin"]))
assert r2["started"][0]["already_running"] is True, r2
assert len(created) == 2, created

# Stop must clear all tracked runs so a new run can start immediately.
mod._stop_one_process = lambda portal, proc: (setattr(proc, "rc", 0) or mod.RUN_PROCESSES.pop(portal, None) or 0)
mod.stop_automation()
assert not mod.RUN_PROCESSES, mod.RUN_PROCESSES
r3 = mod.start_automation(mod.RunBody(portals=["naukri"]))
assert r3["started"][0]["already_running"] is False, r3
assert len(created) == 3, created

mod.subprocess.Popen = orig_popen
mod._port_open = orig_port_open
print("V19 concurrency/restart tests: PASS")
