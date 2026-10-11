import sqlite3
from pathlib import Path

DB = Path("applications.db")

def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS applications(
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
    )""")
    cols = {row[1] for row in con.execute("PRAGMA table_info(applications)").fetchall()}
    migrations = {
        'job_key': "ALTER TABLE applications ADD COLUMN job_key TEXT",
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

def seen(con, url):
    return con.execute("SELECT 1 FROM applications WHERE job_url=?", (url,)).fetchone() is not None

def app(con, url, title, status, company="", location="", description="", match_score=None, eligible=None, matched_skills=None):
    skills = ", ".join(str(x) for x in (matched_skills or []) if str(x).strip())
    con.execute(
        "INSERT OR REPLACE INTO applications(job_url,job_key,title,status,company,location,description,match_score,eligible,matched_skills) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (url, url, title, status, company or "", location or "", description or "", match_score, None if eligible is None else int(bool(eligible)), skills),
    )
    con.commit()

def qa(con, url, question, answer, field):
    con.execute("INSERT INTO qa(job_url,question,answer,field) VALUES(?,?,?,?)",
                (url, question, answer, field))
    con.commit()


def _normalize_custom_question(text):
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(text or "").lower())).strip()


def save_custom_qa(question, answer):
    q, a = str(question or "").strip(), str(answer or "").strip()
    if not q or not a:
        raise ValueError("question and answer are required")
    con = db()
    key = _normalize_custom_question(q)
    con.execute(
        "INSERT INTO custom_qa(question,question_norm,answer,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) "
        "ON CONFLICT(question_norm) DO UPDATE SET question=excluded.question,answer=excluded.answer,updated_at=CURRENT_TIMESTAMP",
        (q, key, a),
    )
    con.commit(); con.close()


def list_custom_qa():
    con=db()
    rows=con.execute("SELECT id,question,answer,created_at,updated_at FROM custom_qa ORDER BY updated_at DESC,id DESC").fetchall()
    con.close()
    return [{"id":r[0],"question":r[1],"answer":r[2],"created_at":r[3],"updated_at":r[4]} for r in rows]


def delete_custom_qa(question_or_id):
    con=db()
    if str(question_or_id).isdigit():
        con.execute("DELETE FROM custom_qa WHERE id=?", (int(question_or_id),))
    else:
        con.execute("DELETE FROM custom_qa WHERE question_norm=?", (_normalize_custom_question(question_or_id),))
    count=con.total_changes; con.commit(); con.close(); return count


def find_custom_answer(question, options=None, threshold=0.82):
    from difflib import SequenceMatcher
    qn=_normalize_custom_question(question)
    if not qn: return None
    con=db(); rows=con.execute("SELECT question,question_norm,answer FROM custom_qa").fetchall(); con.close()
    best=None; best_score=0.0; qt=set(qn.split())
    for qtext,stored,answer in rows:
        ratio=SequenceMatcher(None,qn,stored).ratio()
        st=set(stored.split())
        overlap=len(qt&st)/max(1,len(qt|st)) if qt and st else 0.0
        score=max(ratio,overlap)
        if score>best_score: best_score,best=score,(qtext,answer)
    if best is None or best_score < threshold: return None
    answer=best[1]
    if options:
        normalized={_normalize_custom_question(x):x for x in options if str(x).strip()}
        wanted=_normalize_custom_question(answer)
        if wanted in normalized: answer=normalized[wanted]
        else:
            partial=next((v for k,v in normalized.items() if wanted in k or k in wanted),None)
            if partial is None: return None
            answer=partial
    return {"answer":answer,"question":best[0],"score":best_score}
