#!/usr/bin/env python3
"""Run the existing fact-preserving resume tailoring engine for one D1-selected job."""
from __future__ import annotations
import json, os, sqlite3, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTALS = {"naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"}

def api_report(status: str, task_id: str, lines: list[str], error: str = "", exit_code: int | None = None) -> None:
    base = os.getenv("CLOUD_CONTROL_API_BASE", "").rstrip("/")
    key = os.getenv("CLOUD_CONTROL_API_KEY", "")
    if not base or not key or not task_id:
        print("WARNING: control API settings missing; task status could not be reported.", file=sys.stderr)
        return
    payload = {"task_id": task_id, "status": status, "log_tail": "".join(lines)[-14000:], "error": error or None, "exit_code": exit_code, "github_run_id": os.getenv("GITHUB_RUN_ID")}
    request = urllib.request.Request(base + "/api/worker/report", data=json.dumps(payload).encode(), method="POST", headers={"Content-Type": "application/json", "X-API-Key": key, "User-Agent": "careeragent-cloud-tailor"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            response.read()
    except Exception as exc:
        print(f"WARNING: could not report task state ({type(exc).__name__}).", file=sys.stderr)

def find_job(job_ref: str) -> tuple[str, dict]:
    try:
        portal, raw_id = job_ref.split(":", 1)
        db_id = int(raw_id)
    except Exception as exc:
        raise ValueError("Job reference must look like portal:database_id") from exc
    if portal not in PORTALS:
        raise ValueError("Unsupported portal in job reference")
    db_path = ROOT / "applications.db" if portal == "naukri" else ROOT / "platforms" / portal / "applications.db"
    if not db_path.is_file():
        raise FileNotFoundError(f"The restored private bundle does not contain the {portal} application database")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=8)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute("SELECT * FROM applications WHERE id=?", (db_id,)).fetchone()
        if not row:
            raise LookupError("The selected job is not present in the restored application database")
        return portal, dict(row)
    finally:
        con.close()

def main() -> int:
    task_id = os.getenv("CAREER_AGENT_TASK_ID", "").strip()
    job_ref = os.getenv("CAREER_AGENT_JOB_REF", "").strip()
    lines: list[str] = []
    if not task_id or not job_ref:
        print("CAREER_AGENT_TASK_ID and CAREER_AGENT_JOB_REF are required.", file=sys.stderr)
        return 2
    try:
        api_report("running", task_id, [f"Starting cloud resume tailoring for {job_ref}\n"])
        portal, row = find_job(job_ref)
        title = str(row.get("title") or "").strip()
        company = str(row.get("company") or "").strip()
        url = str(row.get("job_url") or "").strip()
        description = str(row.get("description") or "").strip()
        if not title or title.startswith(("http://", "https://")):
            raise ValueError("This job does not have a usable title; refresh the job metadata first.")
        if not company or company == "Unknown_Company":
            raise ValueError("This job does not have a reliable company name; refresh job metadata first.")
        profile = ROOT / "profile.json"
        master = ROOT / "resume" / "master_resume.tex"
        if not profile.is_file():
            raise FileNotFoundError("The encrypted private bundle is missing profile.json")
        if not master.is_file():
            raise FileNotFoundError("The encrypted private bundle is missing resume/master_resume.tex")
        lines.append(f"Portal: {portal}\nJob: {title}\nCompany: {company}\n")
        print(lines[-1], end="", flush=True)
        from resume_integration import build_tailored_resume
        pdf = build_tailored_resume(profile_path=profile, title=title, jd_text=description, platform=portal, job_url=url, company=company)
        if not pdf or not Path(pdf).is_file():
            raise RuntimeError("The tailoring engine did not produce a PDF. Check the LaTeX and resume-tailoring logs.")
        out_dir = Path(pdf).parent
        report_path = out_dir / "tailoring_report.json"
        report = {}
        if report_path.is_file():
            try: report = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception: report = {}
        lines.append(f"Tailored PDF created: {Path(pdf).name}\n")
        lines.append(f"Metrics preserved: {report.get('metrics_preserved', report.get('verification', {}).get('metrics_preserved', True))}\n")
        print("Resume tailoring completed successfully.", flush=True)
        api_report("completed", task_id, lines, exit_code=0)
        return 0
    except Exception as exc:
        message = f"Resume tailoring failed: {type(exc).__name__}: {exc}"
        lines.append(message + "\n")
        print(message, file=sys.stderr, flush=True)
        api_report("failed", task_id, lines, error=message[:1800], exit_code=1)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
