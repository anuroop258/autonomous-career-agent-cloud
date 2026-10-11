from __future__ import annotations

"""FastAPI adapter for THIS job-agent repository.

This adapter deliberately talks to the existing project files/DB and launches
its real ``main.py`` entrypoint. It does not duplicate the LinkedIn/Indeed/
Naukri application logic.
"""
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import hmac
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
DB_ROOT = ROOT / "applications.db"
WEB_RUNTIME = ROOT / "webapp" / "runtime"
WEB_RUNTIME.mkdir(parents=True, exist_ok=True)
INDEED_HUMAN_MARKER = WEB_RUNTIME / "indeed_human_verification.json"
INDEED_HUMAN_SIGNAL = WEB_RUNTIME / "indeed_human_verification.signal"

# ---------------------------------------------------------------- remote access
# Set CAREER_AGENT_API_KEY to protect every /api/* endpoint (required before you expose
# this server through a tunnel). With no key set the app behaves exactly as before and is
# only reachable from this PC. CORS is limited to the local UI by default; add extra
# origins with CAREER_AGENT_ALLOWED_ORIGINS="https://a.example,https://b.example".
API_KEY = os.getenv("CAREER_AGENT_API_KEY", "").strip()
AUTH_ON = bool(API_KEY)
# Cloud mode runs a managed, headless Chromium instance in this container. Portal
# authentication is imported explicitly through /api/browser/session/import; the app
# never tries to attach to the user's local Windows Chrome from the cloud.
CLOUD_MODE = os.getenv("CAREER_AGENT_CLOUD", "").strip() == "1"
CLOUD_BROWSER_MODE = os.getenv("CAREER_AGENT_CLOUD_BROWSER", "1").strip() == "1"
# In split cloud mode this process serves HTTP only. The separate Render worker
# owns Chromium and runs the existing main.py <portal> entrypoint.
CLOUD_SPLIT_MODE = CLOUD_MODE and os.getenv("CAREER_AGENT_EXECUTION_MODE", "").strip().lower() == "queue"
DATA_DIR = Path(os.getenv("DATA_DIR", "/data" if CLOUD_MODE else str(ROOT)))
BROWSER_SESSION_DIR = DATA_DIR / "browser_sessions"
BROWSER_PROFILE_DIR = DATA_DIR / "browser_profiles"


def _local_only(what: str) -> None:
    if CLOUD_MODE and not CLOUD_BROWSER_MODE:
        raise HTTPException(
            status_code=501,
            detail=f"{what} is disabled because CAREER_AGENT_CLOUD_BROWSER=0.",
        )
if AUTH_ON and len(API_KEY) < 16:
    raise RuntimeError("CAREER_AGENT_API_KEY must be at least 16 characters.")
ALLOWED_ORIGINS = [
    "http://127.0.0.1:5175", "http://localhost:5175",
    "http://127.0.0.1:8001", "http://localhost:8001",
] + [o.strip() for o in os.getenv("CAREER_AGENT_ALLOWED_ORIGINS", "").split(",") if o.strip()]

app = FastAPI(
    title="Autonomous Career Agent Control Panel", version="1.0.0",
    # Hide the API schema from the internet while a key is enforced.
    docs_url=None if AUTH_ON else "/docs",
    redoc_url=None if AUTH_ON else "/redoc",
    openapi_url=None if AUTH_ON else "/openapi.json",
)

_OPEN_API_PATHS = {"/api/health", "/api/auth/status"}
_FAILED_KEYS: dict[str, list[float]] = {}
_MAX_FAILS, _FAIL_WINDOW = 10, 300.0


@app.on_event("startup")
def _initialize_split_cloud_mode() -> None:
    if not CLOUD_SPLIT_MODE:
        return
    from cloud_queue import ensure_schema, initialize_shared_snapshot, sync_shared_from_store
    ensure_schema()
    initialize_shared_snapshot()
    sync_shared_from_store(force=True)


@app.middleware("http")
async def _api_key_guard(request, call_next):
    path = request.url.path
    if (not AUTH_ON or request.method == "OPTIONS"
            or not path.startswith("/api") or path in _OPEN_API_PATHS):
        return await call_next(request)

    client = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
    now = time.time()
    recent = [t for t in _FAILED_KEYS.get(client, []) if now - t < _FAIL_WINDOW]
    if len(recent) >= _MAX_FAILS:
        _FAILED_KEYS[client] = recent
        return JSONResponse({"detail": "Too many wrong keys. Try again in a few minutes."}, status_code=429)

    supplied = request.headers.get("x-api-key", "")
    if not supplied:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
    # Browser links (<a href>) cannot send headers, so the resume PDF download alone
    # also accepts ?api_key=.
    if not supplied and request.method == "GET" and path.endswith("/resume-file"):
        supplied = request.query_params.get("api_key", "")

    if supplied and hmac.compare_digest(supplied.encode(), API_KEY.encode()):
        if CLOUD_SPLIT_MODE and path.startswith("/api"):
            from cloud_queue import (
                acquire_shared_mutation_lock, active_task_count,
                push_shared_snapshot, release_shared_mutation_lock, sync_shared_from_store,
            )
            shared_write = (
                path == "/api/qa" or path.startswith("/api/qa/")
                or path.startswith("/api/applications/")
                or path.endswith("/tailor-resume")
                or path.endswith("/refresh-metadata")
            ) and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            mutation_guard = None
            try:
                # Acquire the shared-data lock BEFORE syncing the API's local files.
                # If a worker is finalizing, this waits until its final snapshot is
                # published, preventing an old API snapshot from overwriting new data.
                if shared_write:
                    mutation_guard = acquire_shared_mutation_lock()
                    if active_task_count():
                        return JSONResponse({
                            "detail": "An agent run is using shared application data. Stop or wait for the run to finish, then retry this change."
                        }, status_code=409)

                try:
                    sync_shared_from_store()
                except Exception as exc:
                    return JSONResponse({"detail": f"Shared cloud state is unavailable: {type(exc).__name__}"}, status_code=503)

                response = await call_next(request)
                if shared_write and response.status_code < 400:
                    try:
                        push_shared_snapshot()
                    except Exception as exc:
                        # The write already succeeded locally. Return an error rather than
                        # imply it has replicated to the worker/cloud source of truth.
                        return JSONResponse({"detail": f"Saved locally but cloud replication failed: {type(exc).__name__}"}, status_code=503)
                return response
            finally:
                if mutation_guard is not None:
                    release_shared_mutation_lock(mutation_guard)
        return await call_next(request)
    if supplied:  # only wrong keys count towards the lockout
        recent.append(now)
    _FAILED_KEYS[client] = recent
    return JSONResponse({"detail": "Invalid or missing API key."}, status_code=401)


# Added after the guard so CORS wraps it (401 responses still carry CORS headers).
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

RUN_STATE: dict[str, Any] = {
    "status": "idle",
    "portals": [],
    "started_at": None,
    "pid": None,
    "pids": {},
    "returncode": None,
    "log_file": None,
    "runs": {},
}
# One process per portal. This restores concurrent execution while preserving
# the shared CDP 9222 session used by Naukri/Indeed.
RUN_PROCESSES: dict[str, subprocess.Popen[str]] = {}
RUN_HANDLES: dict[str, Any] = {}

# Short-lived snapshot cache: the UI polls several read-only endpoints at once.
# Without this cache every request re-scans all platform SQLite DBs, resume metadata
# and filesystem state, which makes the dashboard feel like it is constantly loading.
_APP_SNAPSHOT_LOCK = threading.Lock()
_APP_SNAPSHOT_CACHE: list[dict[str, Any]] | None = None
_APP_SNAPSHOT_AT = 0.0
_APP_SNAPSHOT_TTL = 2.5


def _read_json(path: Path, default: Any):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _profile() -> dict[str, Any]:
    for p in (ROOT / "profile.json", ROOT / "platforms" / "linkedin" / "profile.json", ROOT / "platforms" / "indeed" / "profile.json",
              ROOT / "platforms" / "shine" / "profile.json", ROOT / "platforms" / "timesjobs" / "profile.json",
              ROOT / "platforms" / "glassdoor" / "profile.json"):
        if p.exists():
            return _read_json(p, {})
    return {}


def _root_roles() -> list[str]:
    cfg = _read_json(ROOT / "role_config.json", {})
    return list(cfg.get("primary", []))


def _portal_config(portal: str) -> dict[str, Any]:
    if portal == "linkedin":
        cfg = _read_json(ROOT / "platforms" / "linkedin" / "linkedin_config.json", {})
        return {"enabled": True, "mode": "deterministic", "max_per_day": cfg.get("target_native_applications", 20), "cdp_port": 9232,
                "locations": cfg.get("locations", [])}
    if portal == "indeed":
        cfg = _read_json(ROOT / "platforms" / "indeed" / "role_config.json", {})
        return {"enabled": True, "mode": "deterministic", "max_per_day": cfg.get("target_direct_applications", 10), "cdp_port": 9222,
                "locations": []}
    if portal == "naukri":
        cfg = _read_json(ROOT / "role_config.json", {})
        return {"enabled": True, "mode": "deterministic", "max_per_day": cfg.get("target_native_applications", 20), "cdp_port": 9222,
                "locations": cfg.get("locations", [])}
    if portal in {"shine", "timesjobs", "glassdoor"}:
        cfg = _read_json(ROOT / "platforms" / portal / "role_config.json", {})
        cap = cfg.get("target_direct_applications", cfg.get("target_applications", 10))
        return {"enabled": True, "mode": "deterministic", "max_per_day": cap, "cdp_port": 9222,
                "locations": cfg.get("preferred_locations", [])}
    return {"enabled": False, "mode": "unknown", "max_per_day": 0, "cdp_port": 0, "locations": []}


def _connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _ensure_db(path: Path):
    con = _connect(path)
    con.execute("""CREATE TABLE IF NOT EXISTS applications(
        id INTEGER PRIMARY KEY,
        job_url TEXT UNIQUE,
        job_key TEXT,
        title TEXT,
        status TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS custom_qa(
        id INTEGER PRIMARY KEY,
        question TEXT UNIQUE,
        question_norm TEXT UNIQUE,
        answer TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS qa(
        id INTEGER PRIMARY KEY,
        job_url TEXT,
        question TEXT,
        answer TEXT,
        field TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    con.commit()
    return con


def _ensure_application_columns(path: Path):
    """Ensure legacy application DBs expose the metadata fields used by the web UI."""
    con = _connect(path)
    cols = {row[1] for row in con.execute("PRAGMA table_info(applications)").fetchall()}
    migrations = {
        "job_key": "ALTER TABLE applications ADD COLUMN job_key TEXT",
        "company": "ALTER TABLE applications ADD COLUMN company TEXT DEFAULT ''",
        "location": "ALTER TABLE applications ADD COLUMN location TEXT DEFAULT ''",
        "description": "ALTER TABLE applications ADD COLUMN description TEXT DEFAULT ''",
        "match_score": "ALTER TABLE applications ADD COLUMN match_score REAL",
        "eligible": "ALTER TABLE applications ADD COLUMN eligible INTEGER",
        "matched_skills": "ALTER TABLE applications ADD COLUMN matched_skills TEXT DEFAULT ''",
    }
    changed = False
    for name, ddl in migrations.items():
        if name not in cols:
            con.execute(ddl)
            changed = True
    if changed:
        con.commit()
    con.close()


def _infer_naukri_company(title: str = "", url: str = "") -> str:
    """Deterministic fallback for Naukri records when legacy rows predate company capture."""
    title = _safe(title)
    if title and not title.startswith(("http://", "https://")):
        parts = [p.strip() for p in re.split(r"\s+-\s+", title) if p.strip()]
        exp_idx = next((i for i, part in enumerate(parts) if re.search(r"\b\d+\s*(?:to|-|–)\s*\d+\s*(?:years?|yrs?)\b", part, re.I)), None)
        if exp_idx is not None and exp_idx >= 2:
            candidate = parts[exp_idx - 1].strip()
            if candidate and candidate.lower() not in {"indeed", "linkedin", "naukri"}:
                return candidate[:160]
    return ""


async def _live_portal_metadata(job_ref: str) -> dict[str, str]:
    """Read metadata from an already-open portal job tab via its CDP port.

    This is intentionally a metadata refresh only; it does not click, apply, or
    submit anything. It makes legacy DB rows usable in the dashboard without
    changing the frozen application workflows.
    """
    target = _resolve_job_ref(job_ref)
    if not target:
        return {}
    platform = target["platform"]
    wanted = _safe(target.get("job_url"))
    port = int(_portal_config(platform).get("cdp_port") or 0)
    if not wanted or not port:
        return {}
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return {}

    def canon(url: str) -> str:
        return (url or "").split("?", 1)[0].split("#", 1)[0].rstrip("/").lower()

    wanted_c = canon(wanted)
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        except Exception:
            return {}
        try:
            for context in browser.contexts:
                for page in context.pages:
                    if canon(page.url) != wanted_c:
                        continue
                    title = ""
                    company = ""
                    location = ""
                    description = ""
                    if platform == "linkedin":
                        selectors = {
                            "title": ["h1", "h1.t-24", "h1.jobs-unified-top-card__job-title"],
                            "company": [
                                ".job-details-jobs-unified-top-card__company-name a",
                                ".jobs-unified-top-card__company-name a",
                                ".jobs-unified-top-card__company-name",
                                "a[href*='/company/']:visible",
                                "[data-view-name*='job-details-top-card-company' i]",
                                "[data-testid*='company' i]:visible",
                                "[itemprop='hiringOrganization'] [itemprop='name']:visible",
                            ],
                            "description": [
                                ".jobs-description__content",
                                ".jobs-box__html-content",
                                "#job-details",
                                ".jobs-description-content__text",
                            ],
                        }
                    elif platform == "indeed":
                        selectors = {
                            "title": ["h1", "[data-testid='jobsearch-JobInfoHeader-title']", "[data-testid='jobsearch-JobInfoHeader-title-container'] h1"],
                            "company": [
                                "[data-company-name]",
                                "[data-testid='inlineHeader-companyName']",
                                "[data-testid='company-name']",
                                ".jobsearch-InlineCompanyRating-companyHeader",
                                ".jobsearch-CompanyInfoWithoutHeaderImage-companyInfo",
                                ".jobsearch-JobInfoHeader-companyName",
                                "a[data-tn-element='companyName']",
                                "[class*='companyName']",
                                "[itemprop='hiringOrganization'] [itemprop='name']",
                            ],
                            "description": [
                                "#jobDescriptionText",
                                "[data-testid='jobDescriptionText']",
                                ".jobsearch-jobDescriptionText",
                            ],
                        }
                    else:
                        selectors = {
                            "title": ["h1", "h1[class*='jd-header' i]", "div[class*='jobTitle' i]"],
                            "company": [
                                "[data-company-name]",
                                "[data-testid*='company' i]",
                                "[itemprop='hiringOrganization'] [itemprop='name']",
                                "a[href*='/company/']:visible",
                                "a[class*='comp-name']:visible",
                                "a[class*='company']:visible",
                                "div[class*='comp-name']:visible",
                                "span[class*='comp-name']:visible",
                                "div[class*='company']:visible",
                                "span[class*='company']:visible",
                            ],
                            "description": [
                                "[class*='job-desc' i]",
                                "[class*='jobDescription' i]",
                                "[itemprop='description']",
                            ],
                        }
                    for sel in selectors["title"]:
                        try:
                            if await page.locator(sel).count():
                                title = (await page.locator(sel).first.inner_text(timeout=1500)).strip()
                                if title:
                                    break
                        except Exception:
                            pass
                    for sel in selectors["company"]:
                        try:
                            loc = page.locator(sel)
                            for i in range(min(await loc.count(), 10)):
                                candidate = (await loc.nth(i).inner_text(timeout=1000)).strip()
                                if candidate and len(candidate) <= 160 and candidate.lower() not in {"linkedin", "jobs"}:
                                    company = candidate
                                    break
                            if company:
                                break
                        except Exception:
                            pass
                    if not company:
                        try:
                            scripts = page.locator("script[type='application/ld+json']")
                            for i in range(min(await scripts.count(), 15)):
                                raw = (await scripts.nth(i).text_content() or "").strip()
                                if not raw:
                                    continue
                                try:
                                    data = json.loads(raw)
                                except Exception:
                                    continue
                                items = data if isinstance(data, list) else [data]
                                for item in items:
                                    if not isinstance(item, dict):
                                        continue
                                    typ = item.get("@type")
                                    types = typ if isinstance(typ, list) else [typ]
                                    if not any(str(t).lower() == "jobposting" for t in types if t):
                                        continue
                                    org = item.get("hiringOrganization") or item.get("organization") or {}
                                    if isinstance(org, dict):
                                        candidate = _safe(org.get("name"))
                                        if candidate and candidate.lower() not in {"linkedin", "indeed", "naukri", "jobs"} and len(candidate) <= 160:
                                            company = candidate
                                            break
                                if company:
                                    break
                        except Exception:
                            pass
                    if not company and platform == "naukri":
                        company = _infer_naukri_company(title, wanted)

                    for sel in selectors["description"]:
                        try:
                            if await page.locator(sel).count():
                                description = (await page.locator(sel).first.inner_text(timeout=3000)).strip()
                                if description:
                                    break
                        except Exception:
                            pass
                    if not description:
                        try:
                            body = (await page.locator("body").inner_text(timeout=3000)).strip()
                            # Do not store the entire portal chrome as a JD fallback.
                            if len(body) >= 250:
                                description = body
                        except Exception:
                            pass
                    if title or company or description:
                        return {"title": title, "company": company, "location": location, "description": description}
        finally:
            # This is an attach-only metadata read. Do not close the remote
            # Chromium instance or any of the user's portal tabs.
            pass
    return {}


async def _refresh_metadata(job_ref: str) -> dict[str, Any]:
    target = _resolve_job_ref(job_ref)
    if not target:
        raise HTTPException(status_code=404, detail="job/application record not found")
    platform = target["platform"]
    path = next((p for pf, p in _dbs() if pf == platform), None)
    if not path:
        raise HTTPException(status_code=404, detail="application database not found")
    _ensure_application_columns(path)
    meta = await _live_portal_metadata(job_ref)
    if not meta:
        return {"updated": False, "job_ref": job_ref, "message": "No matching open job tab was found on the portal CDP session."}
    con = _connect(path)
    sets = []
    vals = []
    for key in ("title", "company", "location", "description"):
        value = _safe(meta.get(key))
        if value:
            sets.append(f"{key}=?")
            vals.append(value)
    if sets:
        vals.append(int(target["id"]))
        con.execute(f"UPDATE applications SET {', '.join(sets)} WHERE id=?", vals)
        con.commit()
    con.close()
    return {"updated": bool(sets), "job_ref": job_ref, "metadata": meta}


def _dbs() -> list[tuple[str, Path]]:
    paths = [
        ("naukri", DB_ROOT),
        ("linkedin", ROOT / "platforms" / "linkedin" / "applications.db"),
        ("indeed", ROOT / "platforms" / "indeed" / "applications.db"),
        ("shine", ROOT / "platforms" / "shine" / "applications.db"),
        ("timesjobs", ROOT / "platforms" / "timesjobs" / "applications.db"),
        ("glassdoor", ROOT / "platforms" / "glassdoor" / "applications.db"),
    ]
    return [(p, path) for p, path in paths if path.exists()]


def _safe(value: Any) -> str:
    return str(value or "").strip()


def _web_job_ref(platform: str, db_id: int) -> str:
    return f"{platform}:{int(db_id)}"


def _resolve_job_ref(job_ref: str) -> dict[str, Any] | None:
    value = _safe(job_ref)
    if not value:
        return None
    if ":" in value:
        platform, raw_id = value.split(":", 1)
        if platform in {"naukri", "linkedin", "indeed", "shine", "timesjobs", "glassdoor"} and raw_id.isdigit():
            path = next((p for pf, p in _dbs() if pf == platform), None)
            if path and path.exists():
                con = _connect(path)
                row = con.execute("SELECT * FROM applications WHERE id=?", (int(raw_id),)).fetchone()
                con.close()
                if row:
                    return {"platform": platform, **dict(row)}
    # Backward compatibility for old numeric links: only accept an unambiguous match.
    if value.isdigit():
        matches = []
        for platform, path in _dbs():
            con = _connect(path)
            row = con.execute("SELECT * FROM applications WHERE id=?", (int(value),)).fetchone()
            con.close()
            if row:
                matches.append({"platform": platform, **dict(row)})
        if len(matches) == 1:
            return matches[0]
    return None


def _recover_log_metadata(job_url: str, platform: str) -> dict[str, str]:
    """Recover company/role from recent real-agent logs for older DB rows.

    This is only a fallback for records created before metadata columns existed.
    It never guesses from arbitrary page text.
    """
    wanted = _safe(job_url)
    if not wanted:
        return {}
    files = sorted(WEB_RUNTIME.glob(f"run_{platform}_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[:10]:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        current = None
        for line in lines:
            if line.startswith("  JOB CANDIDATE: "):
                current = {"url": line.split(": ", 1)[1].strip()}
                continue
            if not current:
                continue
            if line.startswith("  RESUME COMPANY: "):
                current["company"] = line.split(": ", 1)[1].strip()
            elif line.startswith("  RESUME ROLE: "):
                current["role"] = line.split(": ", 1)[1].strip()
            elif line.startswith("JOB CANDIDATE: ") or line.startswith("SEARCH PAGE "):
                current = None
            if current.get("url") == wanted or current.get("url", "").split("?",1)[0] == wanted.split("?",1)[0]:
                if current.get("company") or current.get("role"):
                    return {k: v for k, v in current.items() if k in {"company", "role"} and v}
    return {}


def _metadata_by_url() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    base = ROOT / "resume_versions"
    if not base.exists():
        return out
    for meta in base.rglob("job_metadata.json"):
        d = _read_json(meta, {})
        url = _safe(d.get("job_url"))
        if url:
            out[url] = {**d, "dir": str(meta.parent)}
    return out


def _all_applications() -> list[dict[str, Any]]:
    global _APP_SNAPSHOT_CACHE, _APP_SNAPSHOT_AT
    now = time.monotonic()
    if _APP_SNAPSHOT_CACHE is not None and (now - _APP_SNAPSHOT_AT) < _APP_SNAPSHOT_TTL:
        return [dict(row) for row in _APP_SNAPSHOT_CACHE]

    with _APP_SNAPSHOT_LOCK:
        now = time.monotonic()
        if _APP_SNAPSHOT_CACHE is not None and (now - _APP_SNAPSHOT_AT) < _APP_SNAPSHOT_TTL:
            return [dict(row) for row in _APP_SNAPSHOT_CACHE]

        result: list[dict[str, Any]] = []
        meta = _metadata_by_url()

        # Build the resume availability index once per snapshot. The old code called
        # _resume_pdf_path_for_url() for every application, which recursively scanned
        # resume_versions for every row (O(applications * resume_records)).
        resume_index: set[tuple[str, ...]] = set()
        try:
            for r in _resume_records():
                raw_pdf = _safe(r.get("pdf"))
                pdf = Path(raw_pdf) if raw_pdf else Path(_safe(r.get("dir"))) / "resume.pdf"
                if not pdf.is_absolute():
                    pdf = ROOT / pdf
                try:
                    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
                        continue
                    url = _normalize_job_url(r.get("job_url"))
                    key = _safe(r.get("job_key"))
                    platform = _safe(r.get("platform")).lower()
                    company = _safe_norm(r.get("company") or "")
                    role = _normalize_resume_role(r.get("role") or "", platform)
                    if url:
                        resume_index.add(("url", url))
                    if key and platform:
                        resume_index.add(("key", platform, key))
                    if key:
                        resume_index.add(("key_any", key))
                    if company and role:
                        resume_index.add(("identity", platform, company, role))
                except OSError:
                    continue
        except Exception:
            resume_index = set()

        for platform, path in _dbs():
            try:
                _ensure_application_columns(path)
                con = _connect(path)
                cols = {r[1] for r in con.execute("PRAGMA table_info(applications)").fetchall()}
                selected = ["id", "job_url", "job_key", "title", "status", "created_at"]
                for extra in ("company", "location", "description", "match_score", "eligible", "matched_skills"):
                    if extra in cols:
                        selected.append(extra)
                rows = con.execute(f"SELECT {', '.join(selected)} FROM applications ORDER BY id DESC").fetchall()
                con.close()
            except sqlite3.Error:
                continue

            for r in rows:
                row = dict(r)
                m = meta.get(_safe(row.get("job_url")), {})
                recovered = _recover_log_metadata(_safe(row.get("job_url")), platform) if not row.get("company") else {}
                company = _safe(row.get("company")) or _safe(m.get("company")) or _safe(recovered.get("company"))
                if not company and platform == "naukri":
                    company = _infer_naukri_company(_safe(row.get("title")), _safe(row.get("job_url")))
                title = _safe(row.get("title"))
                if not title or title.startswith(("http://", "https://")):
                    title = _safe(row.get("role")) or _safe(m.get("role")) or _safe(recovered.get("role")) or "Unknown role"
                status_value = _safe(row.get("status")).lower()
                external_statuses = {
                    "external", "external_filled", "external_submitted", "external_partial",
                    "external_error", "external_blocked", "external_apply_failed",
                    "external_apply_click_failed", "external_apply_not_found",
                    "external_apply_not_reached", "external_skipped",
                }
                native_statuses = {
                    "apply_clicked", "applying", "application_ready", "awaiting_approval",
                    "ready_for_manual_submit", "ready_to_submit", "submitted", "confirmed",
                    "applied", "blocked", "human_intervention", "unknown_question",
                    "no_questions", "answer_not_verified", "resume_upload_failed",
                    "submission_unconfirmed", "submit_not_found", "naukri_apply_error",
                    "application_error", "apply_click_failed", "apply_not_found",
                    "match_found_no_direct_apply",
                }
                if status_value in external_statuses or status_value.startswith("external_"):
                    application_route = "external"
                elif status_value in native_statuses:
                    application_route = "native"
                else:
                    application_route = "unknown"

                normalized_url = _normalize_job_url(_safe(row.get("job_url")))
                key = _safe(row.get("job_key"))
                platform_l = _safe(platform).lower()
                company_norm = _safe_norm(company or "")
                role_norm = _normalize_resume_role(title or "", platform_l)
                resume_available = bool(
                    (normalized_url and ("url", normalized_url) in resume_index)
                    or (key and ("key", platform_l, key) in resume_index)
                    or (key and ("key_any", key) in resume_index)
                    or (company_norm and role_norm and ("identity", platform_l, company_norm, role_norm) in resume_index)
                )

                row.update({
                    "platform": platform,
                    "candidate_id": _safe(_profile().get("contact", {}).get("email")) or "default",
                    "db_id": row.get("id"),
                    "job_ref": _web_job_ref(platform, row.get("id")),
                    "job_id": row.get("id"),
                    "company": company or "Unknown_Company",
                    "title": title,
                    "location": _safe(row.get("location")),
                    "description": _safe(row.get("description")),
                    "url": row.get("job_url") or "",
                    "source": platform,
                    "resume_version_id": None,
                    "resume_pdf_available": resume_available,
                    "submitted_at": row.get("created_at") if row.get("status") in {"submitted", "confirmed", "applied"} else None,
                    "last_error": None,
                    "updated_at": row.get("created_at"),
                    "match_score": row.get("match_score"),
                    "eligible": row.get("eligible"),
                    "matched_skills": [x.strip() for x in _safe(row.get("matched_skills")).split(",") if x.strip()],
                    "application_route": application_route,
                })
                result.append(row)

        result.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        _APP_SNAPSHOT_CACHE = [dict(row) for row in result]
        _APP_SNAPSHOT_AT = time.monotonic()
        return [dict(row) for row in result]


def _resume_records() -> list[dict[str, Any]]:
    base = ROOT / "resume_versions"
    out = []
    if not base.exists():
        return out
    for meta in base.rglob("job_metadata.json"):
        d = _read_json(meta, {})
        out.append({**d, "id": int(hashlib.sha256(str(meta).encode()).hexdigest()[:8], 16), "dir": str(meta.parent)})
    return out


def _normalize_job_url(value: Any) -> str:
    """Normalize portal job URLs for stable resume metadata matching."""
    raw = _safe(value)
    if not raw:
        return ""
    raw = raw.split("#", 1)[0].rstrip("/")
    # Query strings often contain tracking/session parameters that do not identify
    # the job itself. Keep stable query parameters for non-tracking URLs.
    try:
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
        parts = urlsplit(raw)
        if parts.query:
            kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                    if not k.lower() in {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "source", "ref", "referral-source"}]
            raw = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), urlencode(kept), ""))
    except Exception:
        pass
    return raw.rstrip("/")


def _resume_pdf_path_for_url(job_url: str, *, platform: str | None = None, job_key: str | None = None, company: str | None = None, role: str | None = None) -> Path | None:
    """Return the newest valid tailored PDF for a stored job, tolerating URL tracking differences."""
    job_url = _normalize_job_url(job_url)
    key = _safe(job_key)
    platform = _safe(platform).lower()
    company_norm = _safe_norm(company or "")
    role_norm = _normalize_resume_role(role or "", platform)
    if not job_url and not key and not (company_norm and role_norm):
        return None
    candidates: list[tuple[float, Path]] = []
    resume_root = (ROOT / "resume_versions").resolve()
    for r in _resume_records():
        meta_url = _normalize_job_url(r.get("job_url"))
        same_url = bool(job_url and meta_url and meta_url == job_url)
        same_key = bool(key and _safe(r.get("job_key")) == key)
        same_platform = bool(platform and _safe(r.get("platform")).lower() == platform)
        meta_company = _safe_norm(r.get("company") or "")
        meta_role = _normalize_resume_role(r.get("role") or "", r.get("platform") or platform)
        same_identity = bool(
            company_norm
            and role_norm
            and meta_company == company_norm
            and meta_role == role_norm
            and (not platform or same_platform)
        )
        if not (same_url or (same_key and same_platform) or (same_key and not platform) or same_identity):
            continue
        raw = _safe(r.get("pdf"))
        pdf = Path(raw) if raw else Path(_safe(r.get("dir"))) / "resume.pdf"
        if not pdf.is_absolute():
            pdf = ROOT / pdf
        try:
            resolved = pdf.resolve()
            if not resolved.is_file() or resolved.suffix.lower() != ".pdf":
                continue
            resolved.relative_to(resume_root)
            candidates.append((resolved.stat().st_mtime, resolved))
        except (OSError, ValueError):
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _resume_pdf_path_for_job(job_ref: str) -> Path | None:
    """Return the newest valid tailored PDF stored for this exact application reference."""
    target = _resolve_job_ref(job_ref)
    if not target:
        return None
    web_ref = _web_job_ref(target["platform"], target["id"])
    row = next((r for r in _all_applications() if r.get("job_ref") == web_ref), None)
    if not row:
        return None
    return _resume_pdf_path_for_url(
        _safe(row.get("url")),
        platform=target.get("platform"),
        job_key=_safe(row.get("job_key")),
        company=_safe(row.get("company")),
        role=_safe(row.get("title")),
    )


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.8):
            return True
    except OSError:
        return False


def _safe_norm(q: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", q.lower())).strip()


def _normalize_resume_role(value: Any, platform: str | None = None) -> str:
    """Normalize stored/job role strings using the same semantics as resume generation."""
    raw = _safe(value)
    p = _safe(platform).lower()
    if not raw:
        return ""
    if p == "indeed":
        raw = re.sub(r"\s+-\s+Indeed\.com\s*$", "", raw, flags=re.I)
        raw = re.sub(r"\s+\|\s+Indeed\.com\s*$", "", raw, flags=re.I)
        parts = [part.strip() for part in re.split(r"\s+-\s+", raw) if part.strip()]
        location_tail = re.compile(
            r"\b(?:India|Haryana|Gujarat|Maharashtra|Telangana|Karnataka|Tamil Nadu|Delhi|Mumbai|Pune|Gurugram|Gurgaon|Hyderabad|Ahmedabad|Bengaluru|Bangalore|Chennai|Noida|Remote|Remote/Hybrid|Hybrid)\b",
            re.I,
        )
        if len(parts) >= 2 and location_tail.search(parts[-1]):
            raw = " - ".join(parts[:-1])
    elif p == "linkedin":
        raw = re.sub(r"\s*\|\s*LinkedIn\s*$", "", raw, flags=re.I)
    return _safe_norm(raw)


# ------------------------------------------------------------------ health/config
@app.get("/api/health")
def health():
    # Never reveal local paths on an internet-facing server.
    if CLOUD_SPLIT_MODE:
        try:
            from cloud_queue import get_service_state
            worker = get_service_state("worker") or {}
            return {"ok": True, "worker_online": bool(worker.get("_fresh") and not worker.get("error")), "worker_error": worker.get("error")}
        except Exception:
            return JSONResponse({"ok": False, "worker_online": False, "detail": "queue database unavailable"}, status_code=503)
    return {"ok": True} if AUTH_ON else {"ok": True, "root": str(ROOT)}


@app.get("/api/auth/status")
def auth_status():
    return {"auth_required": AUTH_ON, "cloud": CLOUD_MODE}


@app.get("/api/auth/check")
def auth_check():
    # Only reachable with a valid key (or when auth is off).
    return {"ok": True}


@app.get("/api/status")
def status():
    if CLOUD_SPLIT_MODE:
        from cloud_queue import get_service_state, recent_tasks
        worker = get_service_state("worker") or {}
        cdp = worker.get("cdp", {})
        checks = [
            {"name": "project_root", "status": "OK" if (ROOT / "main.py").exists() else "FAIL", "detail": "agent code present"},
            {"name": "playwright", "status": "OK" if __import__("importlib.util", fromlist=["find_spec"]).find_spec("playwright") else "WARN", "detail": "installed in worker image"},
            {"name": "worker", "status": "OK" if worker.get("_fresh") and not worker.get("error") else "WARN", "detail": worker.get("worker_id", "waiting for worker heartbeat")},
            {"name": "cdp_9222", "status": "OK" if cdp.get("9222") else "WARN", "detail": "worker Chromium CDP port 9222"},
            {"name": "cdp_9232", "status": "OK" if cdp.get("9232") else "WARN", "detail": "worker Chromium CDP port 9232"},
        ]
        tasks = recent_tasks(20)
        active = [t for t in tasks if t.get("status") in {"queued", "running"}]
        run_status = "running" if any(t.get("status") == "running" for t in active) else ("queued" if active else "idle")
        overall = "FAIL" if any(c["status"] == "FAIL" for c in checks) else ("WARN" if any(c["status"] == "WARN" for c in checks) else "OK")
        return {"overall": overall, "checks": checks, "run": run_status}
    checks = []
    checks.append({"name": "project_root", "status": "OK" if (ROOT / "main.py").exists() else "FAIL", "detail": str(ROOT)})
    checks.append({"name": "master_resume", "status": "OK" if (ROOT / "resume" / "master_resume.tex").exists() else "FAIL", "detail": str(ROOT / "resume" / "master_resume.tex")})
    try:
        import playwright  # noqa: F401
        pw = "installed"
    except Exception:
        pw = "missing"
    checks.append({"name": "playwright", "status": "OK" if pw == "installed" else "WARN", "detail": pw})
    for p in ("naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"):
        port = _portal_config(p)["cdp_port"]
        checks.append({"name": f"cdp_{p}", "status": "OK" if _port_open(port) else "WARN", "detail": f"127.0.0.1:{port}"})
    overall = "FAIL" if any(c["status"] == "FAIL" for c in checks) else ("WARN" if any(c["status"] == "WARN" for c in checks) else "OK")
    return {"overall": overall, "checks": checks, "run": RUN_STATE["status"]}


@app.get("/api/config")
def config():
    profile = _profile()
    roles = _root_roles()
    portals = {p: _portal_config(p) for p in ("naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor")}
    return {
        "candidate_id": _safe(profile.get("candidate_id")) or _safe(profile.get("contact", {}).get("email")) or "default",
        "db_path": str(DB_ROOT),
        "allow_submit": False,
        "max_retries": 0,
        "max_per_day": 20,
        "max_per_platform": 20,
        "titles": roles,
        "locations": [],
        "resume": {
            "tailor": True,
            "use_tailored_for_upload": True,
            "master_resume_path": str(ROOT / "resume" / "master_resume.tex"),
            "ai_rewrite": False,
            "preserve_metrics": True,
            "max_buzzwords": 0,
        },
        "portals": {p: {k: v for k, v in cfg.items() if k != "locations"} for p, cfg in portals.items()},
        "outreach": {"enabled": False, "mode": "disabled", "daily_cap": 0, "followup_days": 0, "max_followups": 0, "auto_recruiter_discovery": False, "search_provider": "none"},
    }


# ------------------------------------------------------------------ browser launcher
PORTAL_LAUNCH = {
    "linkedin": {
        "port": 9232,
        "profile_dir": "LinkedInAgentRealChrome",
        "url": "https://www.linkedin.com/jobs/",
    },
    "naukri": {
        "port": 9222,
        "profile_dir": "NaukriAgentRealChrome",
        "url": "https://www.naukri.com/",
    },
    "indeed": {
        "port": 9222,
        "profile_dir": "NaukriAgentRealChrome",
        "url": "https://in.indeed.com/",
    },
    "shine": {
        "port": 9222,
        "profile_dir": "NaukriAgentRealChrome",
        "url": "https://www.shine.com/",
    },
    "timesjobs": {
        "port": 9222,
        "profile_dir": "NaukriAgentRealChrome",
        "url": "https://www.timesjobs.com/",
    },
    "glassdoor": {
        "port": 9222,
        "profile_dir": "NaukriAgentRealChrome",
        "url": "https://www.glassdoor.co.in/Job/index.htm",
    },
}

def _chrome_executable() -> Optional[str]:
    if CLOUD_MODE:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                executable = p.chromium.executable_path
            if executable and Path(executable).is_file():
                return executable
        except Exception:
            return None
    candidates = [
        os.environ.get("PROGRAMFILES", "") + r"\Google\Chrome\Application\chrome.exe",
        os.environ.get("PROGRAMFILES(X86)", "") + r"\Google\Chrome\Application\chrome.exe",
        os.environ.get("LOCALAPPDATA", "") + r"\Google\Chrome\Application\chrome.exe",
        shutil.which("chrome.exe") or "",
        shutil.which("chrome") or "",
    ]
    for raw in candidates:
        if raw and Path(raw).exists():
            return str(Path(raw))
    return None


class LaunchBody(BaseModel):
    portal: str


class BrowserSessionImportBody(BaseModel):
    portal: str
    storage_state: dict[str, Any]


def _import_cloud_session(portal: str, port: int) -> bool:
    """Apply a previously exported Playwright storage_state to the cloud browser."""
    if not CLOUD_MODE:
        return False
    state_path = BROWSER_SESSION_DIR / f"{portal}.json"
    if not state_path.is_file():
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=8000)
            contexts = browser.contexts
            if not contexts:
                return False
            context = contexts[0]
            cookies = state.get("cookies", [])
            if cookies:
                context.add_cookies(cookies)
            # Restore localStorage for matching origins. Keep navigation limited to
            # origins included in the user's explicitly imported state.
            for origin_item in state.get("origins", []):
                origin = str(origin_item.get("origin", ""))
                if not origin.startswith("https://"):
                    continue
                page = context.new_page()
                try:
                    page.goto(origin, wait_until="domcontentloaded", timeout=12000)
                    entries = origin_item.get("localStorage", [])
                    page.evaluate("entries => { for (const e of entries) localStorage.setItem(e.name, e.value); }", entries)
                except Exception:
                    pass
                finally:
                    page.close()
            browser.close()
        return True
    except Exception as exc:
        print(f"[cloud-session] Could not restore {portal} session: {type(exc).__name__}: {exc}")
        return False


@app.post("/api/browser/session/import")
def import_browser_session(body: BrowserSessionImportBody):
    """Store a Playwright storage_state exported from the user's logged-in browser."""
    if body.portal not in {"naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"}:
        raise HTTPException(status_code=400, detail="unknown portal")
    state = body.storage_state
    if not isinstance(state.get("cookies", []), list) or not isinstance(state.get("origins", []), list):
        raise HTTPException(status_code=400, detail="storage_state must contain cookies and origins arrays")
    if len(json.dumps(state, ensure_ascii=False).encode("utf-8")) > 1_500_000:
        raise HTTPException(status_code=413, detail="browser session export is too large")
    if CLOUD_SPLIT_MODE:
        from cloud_queue import save_browser_session
        save_browser_session(body.portal, state)
    else:
        BROWSER_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        target = BROWSER_SESSION_DIR / f"{body.portal}.json"
        target.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        try:
            target.chmod(0o600)
        except OSError:
            pass
    applied = False
    if CLOUD_MODE and not CLOUD_SPLIT_MODE:
        port = int(_portal_config(body.portal)["cdp_port"])
        if _port_open(port):
            applied = _import_cloud_session(body.portal, port)
    return {"ok": True, "portal": body.portal, "stored": True, "applied_to_running_browser": applied, "note": "Session data is sensitive like a password. If not applied now, it will be applied when the cloud browser launches."}


@app.post("/api/portal/launch")
def launch_portal(body: LaunchBody):
    portal = body.portal.lower().strip()
    if CLOUD_SPLIT_MODE:
        if portal not in PORTAL_LAUNCH:
            raise HTTPException(status_code=400, detail="unknown portal")
        from cloud_queue import get_service_state
        worker = get_service_state("worker") or {}
        if not worker.get("_fresh") or worker.get("error"):
            raise HTTPException(status_code=503, detail="The browser worker is not online yet.")
        port = int(_portal_config(portal)["cdp_port"])
        connected = bool((worker.get("cdp") or {}).get(str(port)))
        if not connected:
            raise HTTPException(status_code=503, detail=f"Cloud Chromium is not connected on port {port}.")
        return {"ok": True, "portal": portal, "port": port, "url": PORTAL_LAUNCH[portal]["url"],
                "already_running": True, "profile_dir": "persistent worker browser profile", "cloud_browser": True}
    _local_only("Launching a portal browser")
    if portal not in PORTAL_LAUNCH:
        raise HTTPException(status_code=400, detail="unknown portal")

    cfg = PORTAL_LAUNCH[portal]
    chrome = _chrome_executable()
    if not chrome:
        raise HTTPException(status_code=500, detail="Chromium executable not found. Check the Playwright browser installation in the cloud image.")

    if CLOUD_MODE:
        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        profile_name = "linkedin" if portal == "linkedin" else "shared-9222"
        user_data = BROWSER_PROFILE_DIR / profile_name
    else:
        local_appdata = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        user_data = Path(local_appdata) / cfg["profile_dir"]
    user_data.mkdir(parents=True, exist_ok=True)

    already = _port_open(cfg["port"])
    # Cloud Chrome is headless and uses persistent profiles on /data. The agent
    # still connects through the same localhost CDP ports it uses in local mode.
    args = [
        chrome,
        f"--remote-debugging-port={cfg['port']}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={user_data}",
        "--profile-directory=Default",
    ]
    if CLOUD_MODE:
        args.extend(["--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-first-run", "--no-default-browser-check"])
    args.append(cfg["url"])
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to launch Chrome: {exc}")

    if CLOUD_MODE and not already:
        deadline = time.time() + 12
        while time.time() < deadline and not _port_open(cfg["port"]):
            time.sleep(0.25)
        if _port_open(cfg["port"]):
            _import_cloud_session(portal, cfg["port"])
    return {
        "ok": True,
        "portal": portal,
        "port": cfg["port"],
        "url": cfg["url"],
        "already_running": already,
        "profile_dir": "persistent cloud browser profile" if CLOUD_MODE else str(user_data),
        "cloud_browser": CLOUD_MODE,
    }


# ------------------------------------------------------------------ CDP
@app.get("/api/cdp/status")
def cdp_status():
    if CLOUD_SPLIT_MODE:
        from cloud_queue import get_service_state
        worker = get_service_state("worker") or {}
        cdp = worker.get("cdp", {})
        return {p: {"port": _portal_config(p)["cdp_port"], "connected": bool(worker.get("_fresh") and cdp.get(str(_portal_config(p)["cdp_port"]))) }
                for p in ("naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor")}
    return {p: {"port": _portal_config(p)["cdp_port"], "connected": _port_open(_portal_config(p)["cdp_port"])} for p in ("naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor")}


@app.post("/api/cdp/test")
def cdp_test(portal: str = Query(...)):
    if CLOUD_SPLIT_MODE:
        if portal not in {"naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"}:
            raise HTTPException(status_code=404, detail="unknown portal")
        from cloud_queue import get_service_state
        worker = get_service_state("worker") or {}
        port = _portal_config(portal)["cdp_port"]
        return {"portal": portal, "port": port, "connected": bool(worker.get("_fresh") and (worker.get("cdp") or {}).get(str(port)))}
    _local_only("The browser connection test")
    if portal not in {"naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"}:
        raise HTTPException(status_code=404, detail="unknown portal")
    port = _portal_config(portal)["cdp_port"]
    return {"portal": portal, "port": port, "connected": _port_open(port)}


# ------------------------------------------------------------------ dashboard/jobs
@app.get("/api/dashboard")
def dashboard():
    apps = _all_applications()
    submitted = sum(1 for a in apps if a.get("status") in {"submitted", "confirmed", "applied", "dry_run_complete"})
    by_portal = {}
    by_company = {}
    by_title = {}
    for a in apps:
        by_portal[a["platform"]] = by_portal.get(a["platform"], 0) + 1
        by_company[a["company"]] = by_company.get(a["company"], 0) + 1
        by_title[a["title"]] = by_title.get(a["title"], 0) + 1
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "candidate_id": config()["candidate_id"],
        "jobs_discovered": len(apps),
        "applications_total": len(apps),
        "applications_submitted": submitted,
        "awaiting_approval": 0,
        "ready_for_manual_submit": sum(1 for a in apps if a.get("status") in {"ready_to_submit", "application_ready"}),
        "rejections": sum(1 for a in apps if "reject" in str(a.get("status", "")).lower()),
        "interviews": 0,
        "pending_approvals": 0,
        "jobs": {"total": len(apps), "discovered_today": len(apps), "discovered_week": len(apps), "discovered_month": len(apps), "applied_today": submitted, "eligible": None,
                 "by_portal": [{"name": k, "count": v} for k,v in by_portal.items()],
                 "by_company": [{"name": k, "count": v} for k,v in sorted(by_company.items(), key=lambda x:x[1], reverse=True)[:20]],
                 "by_title": [{"name": k, "count": v} for k,v in sorted(by_title.items(), key=lambda x:x[1], reverse=True)[:20]]},
        "applications": {"total": len(apps), "submitted": submitted, "by_status": {}, "by_portal": [], "funnel": []},
        "outreach": {"drafts": 0, "approved_unsent": 0, "sent": 0, "replied": 0, "response_rate": 0, "positive": 0, "negative": 0, "action_required": 0, "send_failed": 0, "pending_followups": 0},
        "top_jobs": sorted(apps, key=lambda x: (x.get("match_score") is not None, x.get("match_score") or -1), reverse=True)[:6],
        "recent_applications": apps[:8],
        "needs_attention": [a for a in apps if a.get("status") in {"error", "unknown_question", "ready_to_submit", "no_questions", "external_error"}][:12],
    }


@app.get("/api/analytics")
def analytics():
    apps = _all_applications()
    return {"applications_by_status": {}, "applications": len(apps), "resumes": len(_resume_records()), "cdp": cdp_status()}


@app.get("/api/dashboard/needs-attention")
def needs_attention(limit: int = 50):
    return [a for a in _all_applications() if a.get("status") in {"error", "unknown_question", "ready_to_submit", "no_questions", "external_error"}][:max(1, min(limit, 100))]


@app.get("/api/jobs")
def jobs(portal: Optional[str] = None, eligible: Optional[bool] = None, q: Optional[str] = None, limit: int = 200, offset: int = 0):
    rows = _all_applications()
    if portal:
        rows = [r for r in rows if r["platform"] == portal]
    if q:
        qn = q.lower()
        rows = [r for r in rows if qn in r["title"].lower() or qn in r["company"].lower()]
    return rows[offset:offset+limit]


@app.post("/api/jobs/{job_ref}/refresh-metadata")
async def refresh_job_metadata(job_ref: str):
    return await _refresh_metadata(job_ref)


@app.get("/api/jobs/{job_ref}")
def job(job_ref: str):
    target = _resolve_job_ref(job_ref)
    if not target:
        raise HTTPException(status_code=404, detail="job/application record not found")
    row = next((r for r in _all_applications() if r.get("job_ref") == _web_job_ref(target["platform"], target["id"])), None)
    if not row:
        raise HTTPException(status_code=404, detail="job/application record not found")
    resumes = [r for r in _resume_records() if _safe(r.get("job_url")) == _safe(row.get("url"))]
    return {"job": row, "matches": [], "applications": [row], "resume_versions": resumes, "events": []}


# ------------------------------------------------------------------ resumes
@app.post("/api/jobs/{job_ref}/tailor-resume")
def tailor_resume(job_ref: str):
    target = _resolve_job_ref(job_ref)
    if not target:
        raise HTTPException(status_code=404, detail="job/application record not found")
    row = next((r for r in _all_applications() if r.get("job_ref") == _web_job_ref(target["platform"], target["id"])), None)
    if not row:
        raise HTTPException(status_code=404, detail="job/application record not found")
    company = _safe(row.get("company"))
    title = _safe(row.get("title"))
    if company in {"", "Unknown_Company"}:
        recovered = _recover_log_metadata(_safe(row.get("url")), _safe(row.get("platform")))
        company = _safe(recovered.get("company")) or company
        title = _safe(recovered.get("role")) or title
        if row.get("platform") == "naukri" and not company:
            company = _infer_naukri_company(title, _safe(row.get("url")))
    if not company or company == "Unknown_Company":
        raise HTTPException(status_code=409, detail="Company name is not available for this job record yet. Run the portal agent once to capture job metadata, then tailor the resume.")
    if not title or title.startswith(("http://", "https://")):
        raise HTTPException(status_code=409, detail="Job title is not available for this job record yet. Open the job and refresh the Jobs page.")
    try:
        sys.path.insert(0, str(ROOT))
        from resume_integration import build_tailored_resume
        pdf = build_tailored_resume(
            profile_path=ROOT / "profile.json",
            title=title,
            jd_text=row.get("description", "") or "",
            platform=row.get("platform", ""),
            job_url=row.get("url", ""),
            company=company,
        )
        if not pdf:
            raise RuntimeError("resume build did not produce a PDF")
        report_path = Path(pdf).with_name("tailoring_report.json")
        report = {}
        if report_path.exists():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:
                report = {}
        return {
            "version_id": int(hashlib.sha256(str(pdf).encode()).hexdigest()[:8], 16),
            "tex_path": str(Path(pdf).with_suffix('.tex')),
            "pdf_path": pdf,
            "matched_skills": row.get("matched_skills", []),
            "compile_error": None,
            "metrics_preserved": True,
            "company": company,
            "role": title,
            "job_ref": row.get("job_ref"),
            "tailoring_report": report,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/jobs/{job_ref}/resume")
def resume_for(job_ref: str):
    target = _resolve_job_ref(job_ref)
    if not target:
        raise HTTPException(status_code=404, detail="record not found")
    row = next((r for r in _all_applications() if r.get("job_ref") == _web_job_ref(target["platform"], target["id"])), None)
    if not row:
        raise HTTPException(status_code=404, detail="record not found")
    return {"versions": [r for r in _resume_records() if _safe(r.get("job_url")) == _safe(row.get("url"))]}


@app.get("/api/jobs/{job_ref}/resume-file")
def resume_file(job_ref: str):
    pdf = _resume_pdf_path_for_job(job_ref)
    if not pdf:
        raise HTTPException(status_code=404, detail="No tailored PDF is stored for this application yet. Use Tailor Resume first.")
    return FileResponse(
        path=pdf,
        media_type="application/pdf",
        filename=pdf.name,
        content_disposition_type="inline",
    )


@app.get("/api/resume/master")
def master_resume():
    path = ROOT / "resume" / "master_resume.tex"
    return {"path": str(path), "content": path.read_text(encoding="utf-8") if path.exists() else ""}


@app.get("/api/resume/content-bank")
def resume_content_bank():
    path = ROOT / "resume_content_bank.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="resume content bank not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"could not read resume content bank: {exc}")


# ------------------------------------------------------------------ applications
@app.get("/api/applications")
def applications(status: Optional[str] = None, limit: int = 200, offset: int = 0):
    rows = _all_applications()
    rows = [r for r in rows if not status or r.get("status") == status]
    return rows[max(0, offset):max(0, offset) + max(1, min(limit, 500))]


@app.get("/api/applications/{application_id}")
def application(application_id: int):
    row = next((r for r in _all_applications() if int(r["id"]) == application_id), None)
    if not row:
        raise HTTPException(status_code=404, detail="application not found")
    return {"application": row, "events": [], "questions": []}


@app.post("/api/applications/{application_id}/mark-submitted")
def mark_submitted(application_id: int):
    for platform, path in _dbs():
        con = _connect(path)
        row = con.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone()
        if row:
            con.execute("UPDATE applications SET status='submitted' WHERE id=?", (application_id,))
            con.commit(); con.close(); return {"ok": True}
        con.close()
    raise HTTPException(status_code=404, detail="application not found")


# ------------------------------------------------------------------ custom Q&A (real project memory)
@app.get("/api/qa")
def list_qa():
    con = _ensure_db(DB_ROOT)
    rows = [dict(r) for r in con.execute("SELECT id, question, answer, created_at, updated_at FROM custom_qa ORDER BY updated_at DESC, id DESC").fetchall()]
    con.close()
    return rows


class QABody(BaseModel):
    question: str
    answer: str


@app.post("/api/qa")
def save_qa(body: QABody):
    q, a = body.question.strip(), body.answer.strip()
    if not q or not a:
        raise HTTPException(status_code=400, detail="question and answer are required")
    con = _ensure_db(DB_ROOT)
    qn = _safe_norm(q)
    con.execute("INSERT INTO custom_qa(question,question_norm,answer,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(question_norm) DO UPDATE SET question=excluded.question, answer=excluded.answer, updated_at=CURRENT_TIMESTAMP", (q, qn, a))
    con.commit(); con.close()
    return {"ok": True}


@app.delete("/api/qa/{qa_id}")
def delete_qa(qa_id: int):
    con = _ensure_db(DB_ROOT)
    cur = con.execute("DELETE FROM custom_qa WHERE id=?", (qa_id,))
    con.commit(); con.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Q&A entry not found")
    return {"ok": True}


# ------------------------------------------------------------------ automation
class RunBody(BaseModel):
    portals: list[str] = []


def _indeed_human_waiting() -> bool:
    return INDEED_HUMAN_MARKER.exists()


def _clear_indeed_human_wait_files() -> None:
    for path in (INDEED_HUMAN_MARKER, INDEED_HUMAN_SIGNAL):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _refresh_run_state() -> None:
    """Reconcile finished portal processes into the aggregated dashboard state."""
    finished = []
    for portal, proc in list(RUN_PROCESSES.items()):
        rc = proc.poll()
        if rc is not None:
            finished.append((portal, rc))
            handle = RUN_HANDLES.pop(portal, None)
            if handle:
                try:
                    handle.close()
                except OSError:
                    pass
            RUN_PROCESSES.pop(portal, None)
            run_info = RUN_STATE.get("runs", {}).get(portal, {})
            run_info["status"] = "idle"
            run_info["returncode"] = rc
            run_info["human_verification"] = False
            RUN_STATE.setdefault("runs", {})[portal] = run_info
            if portal == "indeed":
                _clear_indeed_human_wait_files()

    active = []
    pids: dict[str, int] = {}
    runs = RUN_STATE.setdefault("runs", {})
    for portal, proc in RUN_PROCESSES.items():
        active.append(portal)
        pids[portal] = proc.pid
        info = runs.get(portal, {})
        info.update({"status": "running", "pid": proc.pid})
        if portal == "indeed":
            info["human_verification"] = _indeed_human_waiting()
        runs[portal] = info

    RUN_STATE["portals"] = sorted(active)
    RUN_STATE["pids"] = pids
    RUN_STATE["pid"] = pids.get("linkedin") or pids.get("indeed") or pids.get("naukri")
    if active:
        RUN_STATE["status"] = "running"
    elif RUN_STATE.get("status") == "stopping":
        RUN_STATE["status"] = "idle"
    else:
        RUN_STATE["status"] = "idle"


def _start_one(portal: str) -> dict[str, Any]:
    if portal in RUN_PROCESSES and RUN_PROCESSES[portal].poll() is None:
        return {"portal": portal, "pid": RUN_PROCESSES[portal].pid, "already_running": True}
    if portal == "indeed":
        _clear_indeed_human_wait_files()

    log_path = WEB_RUNTIME / f"run_{portal}_{int(time.time())}.log"
    fh = open(log_path, "a", encoding="utf-8", buffering=1)
    env = os.environ.copy()
    env["JOB_AGENT_PLATFORM"] = portal
    env["JOB_AGENT_CDP_PORT"] = str(_portal_config(portal)["cdp_port"])
    if portal == "indeed":
        env["JOB_AGENT_HUMAN_VERIFICATION_MARKER"] = str(INDEED_HUMAN_MARKER)
        env["JOB_AGENT_HUMAN_VERIFICATION_SIGNAL"] = str(INDEED_HUMAN_SIGNAL)
    popen_kwargs = {
        "cwd": str(ROOT),
        "env": env,
        "stdout": fh,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    # Each portal run gets its own process group so stopping one portal does not
    # terminate any other concurrently running portal.
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen([sys.executable, str(ROOT / "main.py"), portal], **popen_kwargs)
    except Exception:
        try:
            fh.close()
        except OSError:
            pass
        raise

    RUN_PROCESSES[portal] = proc
    RUN_HANDLES[portal] = fh
    RUN_STATE.setdefault("runs", {})[portal] = {
        "status": "running",
        "pid": proc.pid,
        "started_at": time.time(),
        "returncode": None,
        "log_file": str(log_path),
        "human_verification": False,
    }
    return {"portal": portal, "pid": proc.pid, "already_running": False}


@app.post("/api/automation/start")
def start_automation(body: RunBody):
    portals = list(dict.fromkeys([p.lower().strip() for p in (body.portals or ["linkedin"]) if p]))
    if CLOUD_SPLIT_MODE:
        invalid = [p for p in portals if p not in {"naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"}]
        if invalid:
            raise HTTPException(status_code=400, detail=f"unknown portal(s): {', '.join(invalid)}")
        from cloud_queue import enqueue_portal, get_service_state
        worker = get_service_state("worker") or {}
        if not worker.get("_fresh") or worker.get("error") or not all((worker.get("cdp") or {}).get(port) for port in ("9222", "9232")):
            raise HTTPException(status_code=503, detail="The cloud browser worker/Chromium is not ready. Check the career-worker service before starting a run.")
        started = []
        for portal in portals:
            task = enqueue_portal(portal)
            started.append({"portal": portal, "task_id": task["task_id"], "status": task["status"],
                            "already_running": bool(task.get("already_active")), "pid": task.get("child_pid")})
        return {"ok": True, "started": started, "pids": {}, "portals": [p["portal"] for p in started]}
    _local_only("Running the apply agents")
    _refresh_run_state()
    invalid = [p for p in portals if p not in {"naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"}]
    if invalid:
        raise HTTPException(status_code=400, detail=f"unknown portal(s): {', '.join(invalid)}")

    started = []
    for portal in portals:
        started.append(_start_one(portal))
    _refresh_run_state()
    return {"ok": True, "started": started, "pids": RUN_STATE["pids"], "portals": RUN_STATE["portals"]}


def _stop_one_process(portal: str, proc: subprocess.Popen[str], timeout: float = 8.0) -> int | None:
    """Stop exactly one portal process tree; Chrome/CDP is intentionally not a child."""
    pid = proc.pid
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if proc.poll() is None:
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
        rc = proc.returncode if proc.returncode is not None else result.returncode
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            try:
                proc.terminate()
            except OSError:
                pass
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        rc = proc.returncode

    handle = RUN_HANDLES.pop(portal, None)
    if handle:
        try:
            handle.close()
        except OSError:
            pass
    RUN_PROCESSES.pop(portal, None)
    RUN_STATE.setdefault("runs", {}).setdefault(portal, {}).update({"status": "idle", "returncode": rc, "human_verification": False})
    if portal == "indeed":
        _clear_indeed_human_wait_files()
    return rc


@app.post("/api/automation/stop")
def stop_automation():
    if CLOUD_SPLIT_MODE:
        from cloud_queue import request_cancel_all
        rows = request_cancel_all()
        return {"ok": True, "stopped": [{"portal": r["portal"], "task_id": r["task_id"], "status": r["status"]} for r in rows],
                "portals": list(dict.fromkeys(r["portal"] for r in rows))}
    _refresh_run_state()
    if not RUN_PROCESSES:
        RUN_STATE.update(status="idle", portals=[], pids={}, pid=None)
        raise HTTPException(status_code=400, detail="no run in progress")

    RUN_STATE["status"] = "stopping"
    stopped = []
    for portal, proc in list(RUN_PROCESSES.items()):
        stopped.append({"portal": portal, "returncode": _stop_one_process(portal, proc)})
    _refresh_run_state()
    return {"ok": True, "stopped": stopped, "portals": RUN_STATE["portals"]}


@app.post("/api/automation/indeed/continue")
def continue_indeed_human_verification():
    if CLOUD_SPLIT_MODE:
        from cloud_queue import request_indeed_continue
        if not request_indeed_continue():
            raise HTTPException(status_code=409, detail="Indeed is not running or not waiting for verification.")
        return {"ok": True, "message": "Continue signal queued for the cloud worker."}
    _local_only("Indeed verification")
    _refresh_run_state()
    proc = RUN_PROCESSES.get("indeed")
    if proc is None or proc.poll() is not None:
        raise HTTPException(status_code=409, detail="Indeed is not running.")
    if not INDEED_HUMAN_MARKER.exists():
        raise HTTPException(status_code=409, detail="Indeed is not waiting for human verification.")
    try:
        INDEED_HUMAN_SIGNAL.touch(exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not signal Indeed to continue: {exc}")
    return {"ok": True, "message": "Indeed resume signal sent."}


@app.get("/api/automation/status")
def automation_status():
    if CLOUD_SPLIT_MODE:
        from cloud_queue import get_service_state, recent_tasks
        tasks = recent_tasks(50)
        active = [t for t in tasks if t.get("status") in {"queued", "running"}]
        runs = {}
        pids = {}
        for task in tasks:
            portal = task["portal"]
            if portal in runs:
                continue
            state = task["status"]
            runs[portal] = {
                "status": state, "task_id": task["task_id"], "pid": task.get("child_pid"),
                "started_at": task.get("started_at"), "returncode": task.get("returncode"),
                "log_tail": task.get("log_tail", ""), "human_verification": bool(task.get("human_verification")),
                "error": task.get("error"), "requested_at": task.get("requested_at"),
            }
            if state == "running" and task.get("child_pid"):
                pids[portal] = task["child_pid"]
        aggregate = "running" if any(t["status"] == "running" for t in active) else ("queued" if active else "idle")
        worker = get_service_state("worker") or {}
        return {"status": aggregate, "portals": list(dict.fromkeys(t["portal"] for t in active)),
                "started_at": next((t.get("started_at") for t in active if t.get("started_at")), None),
                "pid": next(iter(pids.values()), None), "pids": pids, "returncode": None,
                "log_file": None, "runs": runs, "tasks": tasks, "worker": {k: v for k, v in worker.items() if not k.startswith("_")}}
    _refresh_run_state()
    return RUN_STATE


# ------------------------------------------------------------------ logs
@app.get("/api/logs")
def logs(limit: int = 300, event_type: Optional[str] = None, platform: Optional[str] = None):
    if CLOUD_SPLIT_MODE:
        from cloud_queue import recent_tasks
        result = []
        for task in recent_tasks(20):
            if platform and task.get("portal") != platform:
                continue
            for line_no, line in enumerate((task.get("log_tail") or "").splitlines()[-max(1, min(limit, 1000)):]):
                if event_type and event_type.lower() not in line.lower():
                    continue
                result.append({"id": hashlib.sha1(f"{task['task_id']}:{line_no}:{line}".encode()).hexdigest()[:12],
                               "run_id": task["task_id"], "event_type": "stdout", "platform": task["portal"],
                               "job_id": None, "application_id": None, "payload_json": line,
                               "created_at": task.get("heartbeat_at") or task.get("requested_at")})
                if len(result) >= limit:
                    return result
        return result
    files = sorted(WEB_RUNTIME.glob("run_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    lines = []
    for p in files[:6]:
        try:
            content = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        pf = next((x for x in ("naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor") if f"_{x}_" in p.name), None)
        if platform and pf != platform:
            continue
        for line in content[-limit:]:
            if event_type and event_type.lower() not in line.lower():
                continue
            lines.append({"id": hashlib.sha1(f"{p}:{line}".encode()).hexdigest()[:12], "run_id": p.stem, "event_type": "stdout", "platform": pf, "job_id": None, "application_id": None, "payload_json": line, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(p.stat().st_mtime))})
            if len(lines) >= limit:
                return lines
    return lines


@app.get("/api/logs/raw")
def raw_logs(lines: int = 200):
    if CLOUD_SPLIT_MODE:
        from cloud_queue import recent_tasks
        tasks = recent_tasks(20)
        latest = next((t for t in tasks if t.get("log_tail")), None)
        if not latest:
            return {"files": [], "tail": [], "current_file": None}
        tail = (latest.get("log_tail") or "").splitlines()[-max(1, min(lines, 2000)):]
        return {"files": [t["task_id"] for t in tasks], "tail": tail, "current_file": latest["task_id"]}
    files = sorted(WEB_RUNTIME.glob("run_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"files": [], "tail": []}
    latest = files[0]
    return {"files": [p.name for p in files], "tail": latest.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:], "current_file": latest.name}


# Unsupported modules in this current agent are intentionally reported as empty,
# rather than fabricated data.
@app.get("/api/approvals")
def approvals(kind: Optional[str] = None): return []
@app.post("/api/approvals/{approval_id}/{action}")
def approval_action(approval_id: int, action: str): raise HTTPException(status_code=501, detail="Approvals are not implemented in this current agent build")
@app.get("/api/recruiters")
def recruiters(company: Optional[str] = None): return []
@app.post("/api/recruiters/discover")
def discover_recruiters(job_id: Optional[int] = None): return {"discovered": {}}
@app.get("/api/outreach")
def outreach(status: Optional[str] = None): return []
@app.post("/api/outreach/draft")
def outreach_draft(body: dict): raise HTTPException(status_code=501, detail="Outreach is not implemented in this current agent build")
@app.post("/api/outreach/send")
def outreach_send(): raise HTTPException(status_code=501, detail="Outreach is not implemented in this current agent build")
@app.post("/api/followups/run")
def followups(): return {"created": []}


# ---------------------------------------------------------------- serve the UI
# If the frontend has been built (webapp/frontend/dist), this server also serves it, so a
# single address (e.g. one tunnel URL) provides both the page and the API. Must stay last.
FRONTEND_DIST = ROOT / "webapp" / "frontend" / "dist"
if (FRONTEND_DIST / "index.html").exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
