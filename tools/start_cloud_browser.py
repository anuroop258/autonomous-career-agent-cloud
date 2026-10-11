"""Start the Playwright-installed Chromium binary on the CDP port expected by an agent."""
from __future__ import annotations
import argparse, os, subprocess, sys, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

PORTS = {"naukri": 9222, "indeed": 9222, "linkedin": 9232, "shine": 9222, "timesjobs": 9222, "glassdoor": 9222}

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--portal",choices=sorted(PORTS),required=True); args=ap.parse_args()
    port=PORTS[args.portal]
    with sync_playwright() as p: executable=p.chromium.executable_path
    profile=Path(os.getenv("RUNNER_TEMP","/tmp")) / f"career-agent-chrome-{port}"
    profile.mkdir(parents=True,exist_ok=True)
    log_path=Path(os.getenv("RUNNER_TEMP","/tmp")) / f"career-agent-chromium-{port}.log"
    log=log_path.open("ab")
    cmd=[executable,"--headless=new","--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--no-first-run","--no-default-browser-check","--remote-allow-origins=*",f"--remote-debugging-port={port}",f"--user-data-dir={profile}","about:blank"]
    subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
    endpoint=f"http://127.0.0.1:{port}/json/version"
    deadline=time.time()+45
    while time.time()<deadline:
        try:
            with urllib.request.urlopen(endpoint,timeout=2) as response:
                if response.status==200:
                    print(f"Chromium is ready on CDP port {port}."); return 0
        except Exception: pass
        time.sleep(.5)
    try: print(log_path.read_text(encoding="utf-8",errors="replace")[-6000:])
    except Exception: pass
    raise RuntimeError(f"Chromium did not become ready on port {port}; see {log_path}")

if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as exc: print(f"ERROR: {exc}",file=sys.stderr); raise SystemExit(1)
