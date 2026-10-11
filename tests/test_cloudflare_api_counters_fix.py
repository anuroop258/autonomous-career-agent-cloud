from __future__ import annotations
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_expected_cloudflare_api_routes_exist():
    # Exact routes used by the React API client; dynamic route segments are listed in
    # their Pages Functions path form with [param] components.
    expected = {
        "health.js": ROOT / "functions/api/health.js",
        "status.js": ROOT / "functions/api/status.js",
        "config.js": ROOT / "functions/api/config.js",
        "dashboard.js": ROOT / "functions/api/dashboard.js",
        "preferences.js": ROOT / "functions/api/preferences.js",
        "search/jobs.js": ROOT / "functions/api/search/jobs.js",
        "jobs.js": ROOT / "functions/api/jobs.js",
        "jobs/[job_ref].js": ROOT / "functions/api/jobs/[job_ref].js",
        "jobs/[job_ref]/tailor-resume.js": ROOT / "functions/api/jobs/[job_ref]/tailor-resume.js",
        "applications.js": ROOT / "functions/api/applications.js",
        "applications/[id].js": ROOT / "functions/api/applications/[id].js",
        "automation/start.js": ROOT / "functions/api/automation/start.js",
        "automation/stop.js": ROOT / "functions/api/automation/stop.js",
        "automation/status.js": ROOT / "functions/api/automation/status.js",
        "data/sync.js": ROOT / "functions/api/data/sync.js",
        "worker/control.js": ROOT / "functions/api/worker/control.js",
        "worker/report.js": ROOT / "functions/api/worker/report.js",
    }
    missing = [name for name, path in expected.items() if not path.is_file()]
    assert not missing, f"Missing expected Pages Functions routes: {missing}"


def test_d1_migrations_apply_to_empty_sqlite_database():
    # These migrations use the common SQL subset and should be idempotent.
    con = sqlite3.connect(":memory:")
    for path in sorted((ROOT / "migrations").glob("*.sql")):
        con.executescript(path.read_text(encoding="utf-8"))
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {"tasks", "task_details", "jobs", "applications", "app_config", "resume_files", "log_events", "approvals", "outreach", "recruiters"}
    assert expected <= tables
    # Re-running migrations must not destroy or fail on the existing schema.
    for path in sorted((ROOT / "migrations").glob("*.sql")):
        con.executescript(path.read_text(encoding="utf-8"))
    con.close()


def test_middleware_protects_automation_and_integration_routes_but_allows_public_reads():
    src = (ROOT / "functions/_middleware.js").read_text(encoding="utf-8")
    assert '"/api/automation/start"' in src
    assert '"/api/automation/stop"' in src
    assert '"/api/automation/indeed/continue"' in src
    assert '"/api/portal/launch"' in src
    assert "resumeTailoringAction" in src
    assert "tailor-resume" in src
    assert 'pathname === "/api/data/sync"' in src
    assert "DASHBOARD_API_KEY" in src
    assert "AUTOMATION_PASSWORD" in src
    assert "Cloud API route not found or not JSON" in src
    client = (ROOT / "webapp/frontend/src/api/client.ts").read_text(encoding="utf-8")
    assert "Enter your CareerAgent automation password to tailor this resume" in client
    assert 'headers.set("X-Automation-Password", password)' in client


def test_dashboard_counters_derive_from_d1_and_publisher_excludes_filter_only_rows():
    dashboard = (ROOT / "functions/api/dashboard.js").read_text(encoding="utf-8")
    publisher = (ROOT / "tools/publish_dashboard_data.py").read_text(encoding="utf-8")
    assert "COUNT(*) AS n FROM jobs" in dashboard
    assert "COUNT(*) AS n FROM applications" in dashboard
    assert "applications_submitted: submitted" in dashboard
    assert "NON_APPLICATION_STATUSES" in publisher
    assert '"experience_mismatch"' in publisher
    assert '"low_match"' in publisher


def test_public_find_jobs_save_does_not_claim_to_change_local_agent():
    src = (ROOT / "functions/api/preferences.js").read_text(encoding="utf-8")
    assert "synced_to_agent: false" in src
    assert "config_json" in src
    assert "preferences" in src


def test_dashboard_sync_replaces_stale_mirror_without_deleting_user_workflows():
    src = (ROOT / "functions/api/data/sync.js").read_text(encoding="utf-8")
    publisher = (ROOT / "tools/publish_dashboard_data.py").read_text(encoding="utf-8")
    for table in ("applications", "jobs", "custom_qa", "qa", "resume_versions", "resume_files", "log_events", "app_documents"):
        assert f"DELETE FROM {table}" in src
    # These user-maintained sections are intentionally preserved during dashboard resync.
    assert "DELETE FROM outreach" not in src
    assert "DELETE FROM recruiters" not in src
    assert "DELETE FROM approvals" not in src
    assert 'post(args.base, key, {"reset_snapshot": True})' in publisher
