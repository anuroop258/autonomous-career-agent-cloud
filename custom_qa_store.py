from __future__ import annotations
from difflib import SequenceMatcher
from pathlib import Path
import re, sqlite3

DB = Path(__file__).resolve().parent / 'applications.db'


def _db():
    con = sqlite3.connect(DB)
    con.execute('''CREATE TABLE IF NOT EXISTS custom_qa(
        id INTEGER PRIMARY KEY,
        question TEXT UNIQUE,
        question_norm TEXT UNIQUE,
        answer TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    con.commit()
    return con


def normalize_question(text: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', str(text or '').lower())).strip()


def save_custom_qa(question: str, answer: str) -> None:
    q, a = str(question or '').strip(), str(answer or '').strip()
    if not q or not a:
        raise ValueError('question and answer are required')
    con = _db()
    key = normalize_question(q)
    con.execute(
        'INSERT INTO custom_qa(question,question_norm,answer,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) '
        'ON CONFLICT(question_norm) DO UPDATE SET question=excluded.question,answer=excluded.answer,updated_at=CURRENT_TIMESTAMP',
        (q, key, a),
    )
    con.commit(); con.close()


def list_custom_qa():
    con = _db()
    rows = con.execute('SELECT id,question,answer,created_at,updated_at FROM custom_qa ORDER BY updated_at DESC,id DESC').fetchall()
    con.close()
    return [{'id':r[0], 'question':r[1], 'answer':r[2], 'created_at':r[3], 'updated_at':r[4]} for r in rows]


def delete_custom_qa(question_or_id):
    con = _db()
    if str(question_or_id).isdigit():
        con.execute('DELETE FROM custom_qa WHERE id=?', (int(question_or_id),))
    else:
        con.execute('DELETE FROM custom_qa WHERE question_norm=?', (normalize_question(question_or_id),))
    n = con.total_changes; con.commit(); con.close(); return n


def find_custom_answer(question: str, options=None, threshold: float = 0.82, exact_only: bool = False):
    qn = normalize_question(question)
    if not qn:
        return None
    con = _db()
    rows = con.execute('SELECT question,question_norm,answer FROM custom_qa').fetchall()
    con.close()
    best = None; best_score = 0.0; qtokens = set(qn.split())
    # Exact normalized matches are always safe and deterministic.  Callers can
    # request exact_only when a later semantic router owns the question.
    for qtext, stored, answer in rows:
        ratio = SequenceMatcher(None, qn, stored).ratio()
        stokens = set(stored.split())
        overlap = len(qtokens & stokens) / max(1, len(qtokens | stokens)) if qtokens and stokens else 0.0
        score = max(ratio, overlap)
        # A saved question may be a short visible label while the live form
        # exposes the same semantic question through longer helper text.
        # Use content-word coverage conservatively for multi-word saved labels.
        stop = {
            "a", "an", "the", "and", "or", "of", "to", "for", "in", "on",
            "your", "you", "is", "are", "do", "did", "have", "has", "what",
            "when", "where", "why", "how", "can", "could", "would", "will",
            "me", "us", "my", "i", "please", "tell",
        }
        qcore = {x for x in qtokens if x not in stop}
        score_core = {x for x in stokens if x not in stop}
        if stored == qn:
            best_score = 1.0
            best = (qtext, answer)
            continue
        if exact_only:
            continue
        if len(score_core) >= 2:
            overlap_core = qcore & score_core
            coverage = len(overlap_core) / max(1, len(score_core))
            # Fuzzy content matching requires at least two meaningful tokens.
            # A single shared word such as "projects" is NOT enough to reuse a
            # saved answer for a different question like "What are your projects?".
            # Exact/substring phrase matches remain supported below.
            if coverage >= 0.5 and len(overlap_core) >= 2:
                score = max(score, 0.90)
        if len(stored.split()) >= 2 and (stored in qn or qn in stored):
            score = max(score, 0.96)
        if score > best_score:
            best_score, best = score, (qtext, answer)
    if best is None or best_score < threshold:
        return None
    answer = best[1]
    if options:
        normalized = {normalize_question(x): x for x in options if str(x).strip()}
        wanted = normalize_question(answer)
        if wanted in normalized:
            answer = normalized[wanted]
        else:
            partial = next((value for key, value in normalized.items() if wanted in key or key in wanted), None)
            if partial is None:
                return None
            answer = partial
    return {'answer': answer, 'question': best[0], 'score': best_score}
