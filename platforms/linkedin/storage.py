import sqlite3
from pathlib import Path

DB = Path("applications.db")

def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS applications(
        id INTEGER PRIMARY KEY,
        job_url TEXT UNIQUE,
        title TEXT,
        status TEXT,
        company TEXT DEFAULT '',
        location TEXT DEFAULT '',
        description TEXT DEFAULT '',
        match_score REAL,
        eligible INTEGER,
        matched_skills TEXT DEFAULT '',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    cols = {row[1] for row in con.execute("PRAGMA table_info(applications)").fetchall()}
    migrations = {
        'company': "ALTER TABLE applications ADD COLUMN company TEXT DEFAULT ''",
        'location': "ALTER TABLE applications ADD COLUMN location TEXT DEFAULT ''",
        'description': "ALTER TABLE applications ADD COLUMN description TEXT DEFAULT ''",
        'match_score': "ALTER TABLE applications ADD COLUMN match_score REAL",
        'eligible': "ALTER TABLE applications ADD COLUMN eligible INTEGER",
        'matched_skills': "ALTER TABLE applications ADD COLUMN matched_skills TEXT DEFAULT ''",
    }
    for name, ddl in migrations.items():
        if name not in cols:
            con.execute(ddl)
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

def seen(con, url):
    return con.execute("SELECT 1 FROM applications WHERE job_url=?", (url,)).fetchone() is not None

def app(con, url, title, status, company="", location="", description="", match_score=None, eligible=None, matched_skills=None):
    skills = ", ".join(str(x) for x in (matched_skills or []) if str(x).strip())
    con.execute(
        "INSERT OR REPLACE INTO applications(job_url,title,status,company,location,description,match_score,eligible,matched_skills) VALUES(?,?,?,?,?,?,?,?,?)",
        (url, title, status, company or "", location or "", description or "", match_score, None if eligible is None else int(bool(eligible)), skills),
    )
    con.commit()

def qa(con, url, question, answer, field):
    con.execute("INSERT INTO qa(job_url,question,answer,field) VALUES(?,?,?,?)",
                (url, question, answer, field))
    con.commit()
