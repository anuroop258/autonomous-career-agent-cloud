
"""Deterministic full-JD literal keyword matching.

This intentionally looks beyond configured technical skills.  It extracts
content words and useful phrases from the complete JD, including soft-skill
language, then checks exact case-insensitive occurrences in candidate evidence.
It is advisory scoring evidence: role/seniority/experience gates remain the
hard safety controls.
"""
from __future__ import annotations

import re
from collections import Counter


TITLE_METADATA_SPLIT_RE = re.compile(r"\s+(?:-|–|—|\|)\s+")
MALFORMED_TITLE_FRAGMENTS = {"exper", "exp", "yr", "yrs"}
PHRASE_GENERIC = {
    "role", "overview", "engineer", "engineers", "developer", "developers",
    "candidate", "candidates", "seeking", "highly", "skilled", "strong",
    "hands", "experience", "years", "required", "requirements", "responsibilities",
    "qualifications", "qualification", "preferred", "team", "teams", "company",
    "companies", "position", "positions", "work", "working", "environment",
    "develop", "developing", "developed", "design", "designed", "designing",
    "build", "built", "building", "implement", "implemented", "implementing",
    "provide", "provided", "providing", "support", "supports", "supporting",
}
PHRASE_ANCHORS = {
    "ai", "aiml", "ml", "llm", "llms", "rag", "python", "java", "c++", "sql",
    "nlp", "api", "apis", "faiss", "chromadb", "vector", "database", "databases",
    "prompt", "engineering", "agentic", "agents", "automation", "browser",
    "cloud", "aws", "azure", "gcp", "openai", "gemini", "ollama", "fastapi",
    "tensorflow", "pytorch", "scikit", "transformer", "transformers", "deployment",
    "cicd", "ci", "cd", "observability", "monitoring", "evaluation", "production",
    "cross-functional", "communication", "collaboration", "teamwork", "leadership",
    "problem", "solving", "documentation", "stakeholder", "customer", "decision",
    "retrieval", "semantic", "search", "calling", "function",
}
JD_PROTECTED_TERMS = (
    "NumPy", "OpenAI", "PyTorch", "TensorFlow", "FastAPI", "Flask", "ChromaDB",
    "LangChain", "LangGraph", "Streamlit", "Playwright", "SentenceTransformers",
    "MongoDB", "PostgreSQL", "PowerBI", "GitHub", "LinkedIn", "Indeed", "Naukri",
)

PHRASE_SEEDS = {
    "retrieval augmented generation", "retrieval-augmented generation",
    "prompt engineering", "agentic ai", "agentic ai workflows",
    "vector database", "vector databases", "vector db", "vector dbs", "vector search",
    "llm integration", "llm-based", "llm based", "machine learning", "natural language processing", "artificial intelligence", "transformer-based models",
    "rag pipelines", "cloud deployment", "tool function calling", "function calling",
    "ci/cd", "cicd", "observability frameworks", "monitoring frameworks",
    "evaluation frameworks", "production-ready ai", "production-ready ai features",
    "production-grade cloud environments", "cross-functional teams",
    "source citations", "page citations", "semantic retrieval", "azure openai", "prompt context engineering", "rag pipelines", "cross-functional collaboration", "cicd pipelines", "nlp concepts",
    "deterministic decision gates", "dynamic form handling", "root cause analysis",
    "data quality", "customer support", "decision support", "model evaluation",
}

def _role_title(title: str) -> tuple[str, list[str]]:
    raw = str(title or "").strip()
    if not raw:
        return "", []
    parts = [p.strip() for p in TITLE_METADATA_SPLIT_RE.split(raw) if p.strip()]
    return (parts[0] if parts else raw), parts[1:]

# Common grammatical/job-boilerplate words are excluded so the inventory does
# not become a comparison of words such as "the", "will", or "responsibilities".
STOPWORDS = {
    "a","an","and","are","as","at","be","by","can","for","from","has","have","in","into",
    "is","it","its","of","on","or","our","that","the","their","this","to","using","with",
    "we","you","your","will","who","which","what","when","where","how","they","them","these",
    "those","there","here","than","then","also","not","but","both","such","very","more","most",
    "other","other","all","any","each","per","via","within","across","through","over","under",
    "about","against","between","during","before","after","while","without","including","required",
    "preferred","responsibilities","qualifications","qualification","requirements","requirement","role",
    "roles","description","descriptions","overview","key","candidate","candidates","team","teams","company","companies","job","jobs",
    "position","positions","work","working","works","experience","experienced","knowledge","strong",
    "excellent","good","highly","skilled","skill","skills","ability","abilities","hands","hand",
    "develop","developing","developed","design","designed","designing","implement","implemented",
    "implementing","build","built","building","ensure","ensuring","support","supports","supporting",
    "using","use","used","deliver","delivering","delivery","create","creating","created","provide",
    "provided","providing","advanced","modern","future","based","related","related","etc",
}

SOFT_SKILLS = {
    "communication","collaboration","collaborative","teamwork","leadership","problem solving","problem-solving",
    "analytical","analytical thinking","critical thinking","adaptability","adaptable","proactive","initiative",
    "cross functional","cross-functional","stakeholder management","time management","organization","organized",
    "attention to detail","detail oriented","detail-oriented","ownership","accountability","creativity",
    "mentoring","presentation","presentations","interpersonal","negotiation","decision making","decision-making",
    "customer focus","customer focused","written communication","verbal communication",
}


def _normalize_jd_text(text: str) -> str:
    value = str(text or "")
    value = value.replace("|", " ")
    value = value.replace("toolfunction", "tool function")
    value = value.replace("andor", "and/or")
    protected: dict[str, str] = {}
    for idx, term in enumerate(JD_PROTECTED_TERMS):
        key = f"__JDPROTECTED{idx}__"
        if term in value:
            protected[key] = term
            value = value.replace(term, f" {key} ")
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    for key, term in protected.items():
        value = value.replace(key, term)
    value = re.sub(r"\s+", " ", value).strip()
    return value

def _norm(text: str) -> str:
    text = _normalize_jd_text(text)
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = text.lower()
    text = text.replace("&", " and ")
    text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    text = re.sub(r"[^a-z0-9+.#/&-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9+.#/&-]*", _norm(text))


def _content_words(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in _tokens(text):
        token = token.strip(".,;:!?()[]{}\"")
        if len(token) < 3 or token in STOPWORDS or token.isdigit():
            continue
        if re.fullmatch(r"[+.#/&-]+", token):
            continue
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _phrase_candidates(text: str, max_phrases: int = 80) -> list[str]:
    """Extract explicit seed phrases only; never create sliding windows."""
    raw = _normalize_jd_text(text)
    normalized = _norm(raw)
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = re.sub(r"\s+", " ", value.strip(" .,;:!?()[]{}\""))
        n = _norm(value)
        if not n or n in seen:
            return
        seen.add(n)
        candidates.append(value)

    for seed in PHRASE_SEEDS:
        if re.search(rf"(?<![a-z0-9]){re.escape(_norm(seed))}(?![a-z0-9])", normalized):
            add(seed)
    return candidates[:max_phrases]

def extract_full_jd_keywords(title: str, jd_text: str) -> dict:
    role_title, excluded_metadata = _role_title(title)
    body = _normalize_jd_text(jd_text).strip()
    source = body
    singles = _content_words(source)
    phrases = _phrase_candidates(body)
    phrases = list(dict.fromkeys(phrases))
    phrase_tokens = {tok for phrase in phrases for tok in _norm(phrase).split()}
    singles = [s for s in singles if s not in MALFORMED_TITLE_FRAGMENTS and s not in {"db", "dbs", "and/or"} and s not in phrase_tokens]
    soft = [term for term in SOFT_SKILLS if re.search(rf"(?<![a-z0-9]){re.escape(_norm(term))}(?![a-z0-9])", _norm(source))]
    return {
        "single_keywords": singles,
        "phrase_keywords": phrases,
        "all_keywords": singles + [p for p in phrases if p not in singles],
        "soft_skill_keywords": sorted(soft),
        "role_title": role_title,
        "excluded_title_metadata": excluded_metadata,
    }

def exact_match_keywords(keywords: list[str], evidence_text: str) -> dict:
    evidence = _norm(evidence_text)
    matched: list[str] = []
    missing: list[str] = []
    for keyword in keywords:
        k = _norm(keyword)
        if not k:
            continue
        if " " in k or any(ch in k for ch in "+#.&/-"):
            hit = re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", evidence)
        else:
            hit = re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", evidence)
        (matched if hit else missing).append(keyword)
    total = len(matched) + len(missing)
    return {
        "matched": matched,
        "missing": missing,
        "coverage_percent": round((len(matched) / total) * 100, 1) if total else 0.0,
    }


def build_candidate_evidence(profile: dict, master_resume_text: str = "") -> str:
    parts: list[str] = []
    for key in ("skills", "certifications"):
        values = profile.get(key, []) or []
        parts.extend(str(v) for v in values)
    for project in profile.get("projects", []) or []:
        parts.append(str(project.get("title", "")))
        parts.append(str(project.get("details", "")))
    parts.append(master_resume_text or "")
    return "\n".join(parts)
