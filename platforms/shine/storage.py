import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

DB = Path(__file__).resolve().with_name("applications.db")


def canonical_job_key(url: str) -> str:
    """Stable Shine job identity; strip tracking query/fragment noise."""
    value = (url or "").strip()
    try:
        parsed = urlparse(value)
        path = (parsed.path or value).rstrip("/")
        if path:
            return f"shine:{path.lower()}"
    except Exception:
        pass
    return "shine:" + re.sub(r"[?#].*$", "", value).rstrip("/").lower()


def db():
    con = sqlite3.connect(DB)
    con.execute(
        """CREATE TABLE IF NOT EXISTS applications(
            id INTEGER PRIMARY KEY,
            job_url TEXT UNIQUE,
            job_key TEXT,
            title TEXT,
            status TEXT,
            company TEXT DEFAULT '',
            location TEXT DEFAULT '',
            description TEXT DEFAULT '',
            match_score REAL,
            eligible INTEGER,
            matched_skills TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )"""
    )
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
    for name, ddl in migrations.items():
        if name not in cols:
            con.execute(ddl)
    rows = con.execute(
        "SELECT id, job_url FROM applications WHERE job_key IS NULL OR job_key=''"
    ).fetchall()
    for rid, url in rows:
        con.execute("UPDATE applications SET job_key=? WHERE id=?", (canonical_job_key(url), rid))
    con.execute("CREATE INDEX IF NOT EXISTS idx_applications_job_key ON applications(job_key)")
    con.commit()
    return con


def seen(con, url: str) -> bool:
    key = canonical_job_key(url)
    return con.execute(
        "SELECT 1 FROM applications WHERE job_key=? OR job_url=? LIMIT 1",
        (key, url),
    ).fetchone() is not None


def app(con, url, title, status, company="", location="", description="", match_score=None, eligible=None, matched_skills=None):
    key = canonical_job_key(url)
    skills = ", ".join(str(x) for x in (matched_skills or []) if str(x).strip())
    existing = con.execute("SELECT id FROM applications WHERE job_key=? LIMIT 1", (key,)).fetchone()
    values = (
        url,
        key,
        title,
        status,
        company or "",
        location or "",
        description or "",
        match_score,
        None if eligible is None else int(bool(eligible)),
        skills,
    )
    if existing:
        con.execute(
            """UPDATE applications SET job_url=?,job_key=?,title=?,status=?,company=?,location=?,description=?,
               match_score=?,eligible=?,matched_skills=? WHERE id=?""",
            (*values, existing[0]),
        )
    else:
        con.execute(
            """INSERT INTO applications(job_url,job_key,title,status,company,location,description,match_score,eligible,matched_skills)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            values,
        )
    con.commit()
