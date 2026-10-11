#!/usr/bin/env python3
"""Publish the local application's display data into the public CareerAgent D1 dashboard.

Private cookies/browser state and profile.json are deliberately NOT sent here. The website is public,
so this exports jobs, application records, user-created Q&A, master resume/content bank text, resume
version metadata and small PDF attachments the same way any public website API exposes them.
"""
from __future__ import annotations
import argparse, base64, hashlib, json, os, sqlite3, sys, urllib.error, urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PORTALS = ["naukri", "linkedin", "indeed", "shine", "timesjobs", "glassdoor"]

def stable_id(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12], 16)

def safe(value: Any, fallback: str = "") -> str:
    return fallback if value is None else str(value).strip()

def load_json(path: Path, default: Any) -> Any:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default

def split_skills(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)): return [str(x).strip() for x in value if str(x).strip()]
    raw = safe(value)
    if not raw: return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list): return [str(x).strip() for x in parsed if str(x).strip()]
    except Exception: pass
    return [x.strip() for x in raw.split(",") if x.strip()]


NON_ELIGIBLE_STATUSES = {
    "low_match", "experience_mismatch", "security_check", "rejected_by_filter",
}
ELIGIBLE_WORKFLOW_STATUSES = {
    "native_dry_run", "native_flow_stopped", "external_error", "external_partial",
    "external_skipped", "external_blocked", "external_filled", "external_submitted",
    "external_apply_not_reached", "external_apply_failed", "external_apply_click_failed",
    "external_apply_not_found", "unknown_question", "naukri_apply_error", "blocked",
    "application_incomplete", "answer_not_verified", "applied", "submitted", "confirmed",
    "already_applied", "human_intervention", "resume_upload_failed", "application_ready",
    "ready_to_submit", "ready_for_manual_submit", "awaiting_approval", "match_found_no_direct_apply",
    "apply_clicked", "applying", "submission_unconfirmed", "submit_not_found", "apply_not_found",
    "apply_click_failed", "application_error", "error", "external", "no_questions", "dry_run_complete",
}

# The legacy SQLite table is named `applications`, but it stores every discovered job.
# Only statuses indicating an actual application workflow belong in the dashboard's
# applications table; filter-only rows remain jobs and must not inflate application counts.
NON_APPLICATION_STATUSES = {
    "low_match", "experience_mismatch", "security_check", "rejected_by_filter",
    "not_applied", "discovered", "saved", "eligible", "ineligible",
}

SUBMITTED_STATUSES = {"submitted", "confirmed", "applied", "external_submitted"}

def is_application_record(status: str) -> bool:
    normalized = str(status or "").strip().lower()
    if normalized in NON_APPLICATION_STATUSES:
        return False
    if normalized in ELIGIBLE_WORKFLOW_STATUSES or normalized.startswith("external_"):
        return True
    # Unknown states are intentionally not counted as applications until their meaning
    # is explicit. They remain visible in the job inventory, avoiding fabricated totals.
    return False

def normalize_time(value: Any) -> str:
    """Return an ISO timestamp so D1 date/count queries work for legacy epoch values too."""
    from datetime import datetime, timezone
    if value is None or value == "":
        return ""
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().replace(".", "", 1).isdigit()):
            seconds = float(value)
            if seconds > 10_000_000_000:
                seconds /= 1000.0
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        text = str(value).strip()
        if not text:
            return ""
        # Preserve existing ISO strings, normalizing a trailing UTC offset only when parsable.
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (ValueError, TypeError, OverflowError, OSError):
        return str(value).strip()

def infer_eligible(value: Any, status: str) -> int | None:
    """Preserve known boolean values and recover legacy NULLs from explicit matcher outcomes.

    Older SQLite rows often predate the `eligible` column. We only infer 0 for explicit
    matching/experience/security rejections and 1 for known post-match workflow states;
    neutral states such as `not_applied` remain unknown rather than being fabricated.
    """
    if value is not None and str(value).strip() != "":
        try: return 1 if int(value) == 1 else 0
        except (TypeError, ValueError):
            if isinstance(value, bool): return 1 if value else 0
    normalized = str(status or "").strip().lower()
    if normalized in NON_ELIGIBLE_STATUSES: return 0
    if normalized in ELIGIBLE_WORKFLOW_STATUSES or normalized.startswith("external_"): return 1
    return None

def route(status: str) -> str:
    s = (status or "").lower()
    if s.startswith("external_") or s == "external": return "external"
    if s in {"apply_clicked", "applying", "application_ready", "awaiting_approval", "ready_for_manual_submit", "ready_to_submit", "submitted", "confirmed", "applied", "blocked", "human_intervention", "unknown_question", "no_questions", "answer_not_verified", "resume_upload_failed", "submission_unconfirmed", "submit_not_found", "naukri_apply_error", "application_error", "apply_click_failed", "apply_not_found", "match_found_no_direct_apply"}: return "native"
    return "unknown"

def db_paths() -> list[tuple[str, Path]]:
    candidates = [("naukri", ROOT / "applications.db")]
    candidates += [(p, ROOT / "platforms" / p / "applications.db") for p in PORTALS if p != "naukri"]
    return [(portal, path) for portal, path in candidates if path.is_file()]

def metadata_index() -> tuple[dict[str, dict], list[dict], list[dict]]:
    by_url: dict[str, dict] = {}; versions: list[dict] = []; files: list[dict] = []
    base = ROOT / "resume_versions"
    if not base.is_dir(): return by_url, versions, files
    for path in sorted(base.rglob("job_metadata.json")):
        meta = load_json(path, {})
        if not isinstance(meta, dict): continue
        url = safe(meta.get("job_url")); platform = safe(meta.get("platform")).lower()
        if url: by_url[url.split("?",1)[0].rstrip("/")] = {**meta, "_path": str(path.parent)}
    return by_url, versions, files

def build_payloads() -> list[dict]:
    metas, _, _ = metadata_index()
    job_records: list[dict] = []; app_records: list[dict] = []
    custom_qa: dict[str, dict] = {}; qa: list[dict] = []; qa_seen: set[str] = set()
    resume_versions: list[dict] = []; resume_files: list[dict] = []
    app_db_paths = db_paths()
    url_to_job_ref: dict[str, str] = {}
    id_by_ref: dict[str, int] = {}

    for portal, db_path in app_db_paths:
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            con.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            print(f"WARN: skipped {db_path.name} for {portal}: {exc}", file=sys.stderr); continue
        try:
            table_exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='applications'").fetchone()
            if table_exists:
                columns = {r[1] for r in con.execute("PRAGMA table_info(applications)")}
                fields = [c for c in ["id","job_url","job_key","title","status","created_at","company","location","description","match_score","eligible","matched_skills"] if c in columns]
                for raw in con.execute(f"SELECT {','.join(fields)} FROM applications ORDER BY id ASC"):
                    row = dict(raw); db_id = int(row.get("id") or 0); ref = f"{portal}:{db_id}"; ident = stable_id(ref)
                    url = safe(row.get("job_url")); norm_url = url.split("?",1)[0].rstrip("/")
                    meta = metas.get(norm_url, {})
                    title = safe(row.get("title"))
                    if not title or title.startswith(("http://", "https://")): title = safe(meta.get("role"), "Unknown role")
                    company = safe(row.get("company")) or safe(meta.get("company")) or "Unknown_Company"
                    if title == "Unknown role" and meta.get("role"): title = safe(meta.get("role"))
                    status = safe(row.get("status"), "discovered")
                    matched = split_skills(row.get("matched_skills"))
                    pdf_path = Path(safe(meta.get("pdf"))) if meta.get("pdf") else (Path(meta.get("_path", "")) / "resume.pdf" if meta else None)
                    if pdf_path and not pdf_path.is_absolute(): pdf_path = ROOT / pdf_path
                    pdf_ok = bool(pdf_path and pdf_path.is_file() and pdf_path.suffix.lower() == ".pdf")
                    created = normalize_time(row.get("created_at"))
                    is_application = is_application_record(status)
                    submitted = created if status.strip().lower() in SUBMITTED_STATUSES else None
                    eligible_value = infer_eligible(row.get("eligible"), status)
                    j = {"id":ident,"job_ref":ref,"platform":portal,"source":portal,"job_key":safe(row.get("job_key")),"title":title,"company":company,"location":safe(row.get("location")),"description":safe(row.get("description")),"url":url,"discovered_at":created,"updated_at":created,"match_score":row.get("match_score"),"eligible":eligible_value,"matched_skills":matched,"missing_skills":[],"application_id":ident if is_application else None,"application_platform":portal if is_application else None,"application_status":status if is_application else None,"resume_version_id":None,"resume_pdf_available":pdf_ok,"application_route":route(status),"status":status}
                    job_records.append(j); id_by_ref[ref] = ident
                    if is_application:
                        a = {"id":ident,"application_ref":ref,"job_id":ident,"platform":portal,"status":status,"resume_version_id":None,"submitted_at":submitted,"last_error":None,"created_at":created,"updated_at":created,"title":title,"company":company,"location":safe(row.get("location")),"url":url,"source":portal,"eligible":eligible_value,"resume_pdf_available":pdf_ok,"application_route":route(status),"description":safe(row.get("description")),"match_score":row.get("match_score"),"matched_skills":matched}
                        app_records.append(a)
                    if norm_url: url_to_job_ref[norm_url] = ref
            if "custom_qa" in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                for row in con.execute("SELECT id,question,answer,created_at,updated_at FROM custom_qa ORDER BY id"):
                    q = safe(row[1]); a = safe(row[2]);
                    if q: custom_qa[q.lower()] = {"id": stable_id("custom_qa:"+q.lower()), "question":q, "answer":a, "created_at":safe(row[3]), "updated_at":safe(row[4])}
            if "qa" in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                for row in con.execute("SELECT id,job_url,question,answer,field,created_at FROM qa ORDER BY id"):
                    key = f"{portal}:{row[0]}:{safe(row[1])}:{safe(row[2])}"
                    if key in qa_seen: continue
                    qa_seen.add(key); qa.append({"id":stable_id("qa:"+key),"job_url":safe(row[1]),"question":safe(row[2]),"answer":safe(row[3]),"field":safe(row[4]),"created_at":safe(row[5])})
        finally:
            con.close()

    for path in sorted((ROOT / "resume_versions").rglob("job_metadata.json")) if (ROOT / "resume_versions").exists() else []:
        meta = load_json(path, {})
        if not isinstance(meta, dict): continue
        url = safe(meta.get("job_url")); platform = safe(meta.get("platform")).lower()
        job_ref = url_to_job_ref.get(url.split("?",1)[0].rstrip("/"))
        if not job_ref:
            key = safe(meta.get("job_key"))
            candidates = [j for j in job_records if j["platform"] == platform and key and j.get("job_key") == key]
            if candidates: job_ref = candidates[0]["job_ref"]
        if not job_ref: continue
        rid = stable_id("resume:" + job_ref + ":" + path.parent.as_posix())
        report_path = Path(safe(meta.get("tailoring_report"))) if meta.get("tailoring_report") else path.parent / "tailoring_report.json"
        if not report_path.is_absolute(): report_path = ROOT / report_path
        report = load_json(report_path, {}) if report_path.is_file() else {}
        pdf_path = Path(safe(meta.get("pdf"))) if meta.get("pdf") else path.parent / "resume.pdf"
        if not pdf_path.is_absolute(): pdf_path = ROOT / pdf_path
        pdf_ok = pdf_path.is_file() and pdf_path.stat().st_size <= 1_380_000
        resume_versions.append({"id":rid,"job_ref":job_ref,"platform":platform,"company":safe(meta.get("company")),"role":safe(meta.get("role")),"job_url":url,"metadata":meta,"report":report,"pdf_available":bool(pdf_ok),"pdf_filename":pdf_path.name if pdf_ok else "","created_at":safe(meta.get("created_at"), safe(path.stat().st_mtime))})
        if pdf_ok:
            try: resume_files.append({"file_key":f"job:{job_ref}","filename":pdf_path.name,"content_type":"application/pdf","content_b64":base64.b64encode(pdf_path.read_bytes()).decode("ascii")})
            except OSError: pass
    master_pdf = ROOT / "resume" / "master_resume.pdf"
    if master_pdf.is_file() and master_pdf.stat().st_size <= 1_380_000:
        try: resume_files.append({"file_key":"master:pdf","filename":master_pdf.name,"content_type":"application/pdf","content_b64":base64.b64encode(master_pdf.read_bytes()).decode("ascii")})
        except OSError: pass

    role = load_json(ROOT / "role_config.json", {})
    indeed = load_json(ROOT / "platforms" / "indeed" / "role_config.json", {})
    titles = role.get("primary") if isinstance(role.get("primary"), list) else ["GenAI Engineer"]
    locations = role.get("locations") or indeed.get("preferred_locations") or []
    cfg = {"candidate_id":"CareerAgent","db_path":"Cloudflare D1","allow_submit":False,"max_retries":0,"max_per_day":20,"max_per_platform":20,"titles":titles,"locations":locations,"resume":{"tailor":True,"use_tailored_for_upload":True,"master_resume_path":"public-cloud/master_resume.tex","ai_rewrite":False,"preserve_metrics":True,"max_buzzwords":0},"portals":{p:{"enabled":True,"mode":"cloud-runner","max_per_day":20,"cdp_port":9232 if p=="linkedin" else 9222} for p in PORTALS},"outreach":{"enabled":False,"mode":"manual","daily_cap":0,"followup_days":0,"max_followups":0,"auto_recruiter_discovery":False,"search_provider":"none"}}
    documents = {"master_resume_tex": (ROOT / "resume" / "master_resume.tex").read_text(encoding="utf-8") if (ROOT / "resume" / "master_resume.tex").is_file() else "", "resume_content_bank": load_json(ROOT / "resume_content_bank.json", {})}
    logs = []
    run_dir = ROOT / "webapp" / "runtime"
    if run_dir.is_dir():
        for path in sorted(run_dir.glob("*.jsonl"))[-5:]:
            try:
                for index, line in enumerate(path.read_text(encoding="utf-8",errors="replace").splitlines()[-250:]):
                    try: item = json.loads(line)
                    except Exception: continue
                    logs.append({"id":stable_id(f"log:{path.name}:{index}:{line[:120]}"),"run_id":safe(item.get("run_id")),"event_type":safe(item.get("event_type"),"agent_event"),"platform":safe(item.get("platform")),"job_id":None,"application_id":None,"payload_json":json.dumps(item,ensure_ascii=False),"created_at":safe(item.get("created_at"),path.stat().st_mtime)})
            except OSError: pass
    # Small batches keep D1's per-request batch below 100 statements and avoid large API bodies.
    payloads: list[dict] = []
    batch = 40
    for i in range(0,max(len(job_records),len(app_records)),batch):
        payloads.append({"jobs":job_records[i:i+batch],"applications":app_records[i:i+batch]})
    if custom_qa:
        values=list(custom_qa.values())
        for i in range(0,len(values),40): payloads.append({"custom_qa":values[i:i+40]})
    if qa:
        for i in range(0,len(qa),40): payloads.append({"qa":qa[i:i+40]})
    if resume_versions:
        for i in range(0,len(resume_versions),25): payloads.append({"resume_versions":resume_versions[i:i+25]})
    for file in resume_files: payloads.append({"resume_files":[file]})
    if logs:
        for i in range(0,len(logs),40): payloads.append({"logs":logs[i:i+40]})
    payloads.append({"config":cfg,"documents":documents})
    print(f"Prepared {len(job_records)} job records, {len(app_records)} application records, {len(custom_qa)} custom Q&A entries, {len(resume_versions)} resume versions, {len(resume_files)} small PDF files.")
    return payloads

def post(base: str, key: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + "/api/data/sync", data=body, method="POST", headers={"Content-Type":"application/json","X-API-Key":key,"User-Agent":"CareerAgent-dashboard-sync"})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp: return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8","replace")[:1000]
        raise RuntimeError(f"Cloud sync rejected request (HTTP {exc.code}): {text}") from exc

def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base",default=os.getenv("CLOUD_CONTROL_API_BASE","https://autonomous-career-agent-cloud.pages.dev"))
    ap.add_argument("--key-file",type=Path,default=ROOT / "cloud_private" / "dashboard_api_key.txt")
    ap.add_argument("--key-env",action="store_true",help="read internal integration key from CLOUD_CONTROL_API_KEY")
    args=ap.parse_args()
    key=os.getenv("CLOUD_CONTROL_API_KEY","") if args.key_env else (args.key_file.read_text(encoding="ascii").strip() if args.key_file.is_file() else "")
    if not key: print("ERROR: internal sync key missing; provide cloud_private/dashboard_api_key.txt or CLOUD_CONTROL_API_KEY.",file=sys.stderr); return 2
    if not args.base.startswith("https://"): print("ERROR: control API base must use HTTPS.",file=sys.stderr); return 2
    try:
        payloads=build_payloads(); total=0
        # Replace the mirrored dashboard snapshot first so rows from older exports do not
        # inflate totals forever. This is key-protected and leaves preferences/outreach intact.
        reset = post(args.base, key, {"reset_snapshot": True})
        if reset.get("reset") is not True:
            raise RuntimeError("Cloud API did not confirm the dashboard snapshot reset; refusing to report sync success.")
        print("Cleared previous mirrored dashboard rows; publishing a fresh snapshot.")
        for index,payload in enumerate(payloads,1):
            result=post(args.base,key,payload); total+=int(result.get("synced",0))
            print(f"[{index}/{len(payloads)}] Synced {result.get('synced',0)} records")
        print(f"Dashboard data sync complete. {total} records written to Cloudflare D1.")
        return 0
    except Exception as exc:
        print(f"ERROR: Dashboard sync failed: {exc}",file=sys.stderr); return 1
if __name__=="__main__": raise SystemExit(main())
