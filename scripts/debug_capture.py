#!/usr/bin/env python3
"""Collect reproducible debugging evidence without modifying the target project.

Creates a debug-evidence folder containing:
- environment information
- git status/diff (if available)
- Python compile result
- pytest result
- optional user-supplied live-run command result
- Chrome CDP endpoint snapshots for port 9222 when reachable

This script intentionally does not edit source files.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shlex
import subprocess
import sys
import urllib.request
from pathlib import Path


def run(cmd: str, cwd: Path, timeout: int = 1800) -> tuple[int, str, str]:
    p = subprocess.run(
        cmd,
        cwd=str(cwd),
        shell=True,
        text=True,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, p.stdout, p.stderr


def write_result(out: Path, name: str, rc: int, stdout: str, stderr: str) -> None:
    (out / f"{name}.stdout.txt").write_text(stdout, encoding="utf-8")
    (out / f"{name}.stderr.txt").write_text(stderr, encoding="utf-8")
    (out / f"{name}.result.json").write_text(
        json.dumps({"returncode": rc, "ok": rc == 0}, indent=2), encoding="utf-8"
    )


def fetch_json(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return True, r.read().decode("utf-8", errors="replace")
    except Exception as e:  # environment probe; failure is expected when Chrome is not running
        return False, repr(e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".", help="target repository")
    ap.add_argument("--out", default="debug-evidence", help="evidence directory")
    ap.add_argument("--pytest", default="pytest -q", help="pytest command")
    ap.add_argument("--live-command", default="", help="optional live browser/app command")
    args = ap.parse_args()

    project = Path(args.project).resolve()
    out = (project / args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    meta = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "project": str(project),
        "python": sys.version,
        "platform": platform.platform(),
        "cwd": os.getcwd(),
    }
    (out / "environment.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    if (project / ".git").exists():
        for name, cmd in {
            "git_status": "git status --short",
            "git_diff": "git diff --stat && git diff -- . ':(exclude)debug-evidence'",
        }.items():
            rc, so, se = run(cmd, project)
            write_result(out, name, rc, so, se)

    rc, so, se = run(f'"{sys.executable}" -m compileall -q .', project, timeout=600)
    write_result(out, "compileall", rc, so, se)

    rc, so, se = run(args.pytest, project)
    write_result(out, "pytest", rc, so, se)

    for url in ("http://127.0.0.1:9222/json/version", "http://127.0.0.1:9222/json"):
        ok, payload = fetch_json(url)
        slug = "cdp_" + url.rsplit("/", 1)[-1]
        (out / f"{slug}.txt").write_text(payload, encoding="utf-8")
        (out / f"{slug}.result.json").write_text(
            json.dumps({"url": url, "reachable": ok}, indent=2), encoding="utf-8"
        )

    if args.live_command:
        rc, so, se = run(args.live_command, project, timeout=3600)
        write_result(out, "live_run", rc, so, se)

    manifest = {
        "purpose": "Evidence collected before/after debugging; no source files edited by this script.",
        "files": sorted(p.name for p in out.iterdir()),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Evidence written to: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
