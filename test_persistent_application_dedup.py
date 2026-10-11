from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_naukri_uses_persistent_applications_db_dedup_before_processing():
    src = _read("naukri_agent.py")
    assert "from storage import db, seen, app, qa" in src
    marker = 'for url in urls:'
    start = src.index(marker, src.index("async def run_search")) if "async def run_search" in src else src.index(marker)
    block = src[start:start + 1800]
    assert "if seen(self.con, url):" in block
    assert "DB DEDUP -> already processed" in block
    assert "mark_jobs_seen" not in block


def test_linkedin_uses_persistent_applications_db_dedup_before_processing():
    src = _read("platforms/linkedin/linkedin_agent.py")
    assert "from storage import db, seen, app, qa" in src
    marker = 'for url in urls:'
    start = src.index(marker, src.index("async def run_with_context"))
    block = src[start:start + 1800]
    assert "job_key = self.fingerprint(url)" in block
    assert "if seen(self.con, job_key):" in block
    assert "DB DEDUP -> already processed" in block


def test_no_search_history_bulk_marker_feature_is_present():
    for rel in ("naukri_agent.py", "platforms/indeed/indeed_agent.py", "platforms/linkedin/linkedin_agent.py"):
        src = _read(rel)
        assert "mark_jobs_seen" not in src
        assert "job_history" not in src
