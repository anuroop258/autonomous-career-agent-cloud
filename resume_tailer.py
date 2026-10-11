from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


# Grammatical/function words only. Important content words such as
# "documentation", "mathematics", "experience", "communication", "KPIs", and
# domain nouns are intentionally retained in the literal inventory.
GRAMMATICAL_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has", "have",
    "he", "her", "here", "hers", "him", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "itself", "may", "me", "more", "most", "must", "my", "no",
    "not", "of", "on", "or", "our", "ours", "out", "over", "she", "should", "so",
    "some", "such", "than", "that", "the", "their", "theirs", "them", "then", "there",
    "these", "they", "this", "those", "to", "under", "up", "us", "was", "we", "were",
    "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with",
    "would", "you", "your", "yours", "via", "per", "also", "etc", "etc.", "using", "use", "used",
    "role", "roles", "description", "descriptions", "overview", "key", "responsibilities", "qualifications", "qualification",
    "seeking", "highly", "skilled", "ideal", "candidate", "candidates", "preferred", "required", "advanced", "modern", "strong", "deep", "solid",
}

# Job-board titles often append location/company/experience metadata after the
# actual role name. Those tokens are operational metadata, not JD keywords.
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
    "production-grade cloud environments", "cross-functional teams", "cross-functional collaboration",
    "source citations", "page citations", "semantic retrieval",
    "deterministic decision gates", "dynamic form handling", "root cause analysis",
    "data quality", "customer support", "decision support", "model evaluation",
}

def _normalize_jd_delimiters(text: str) -> str:
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

def _role_title_and_excluded_metadata(title: str) -> tuple[str, list[str]]:
    raw = str(title or "").strip()
    if not raw:
        return "", []
    parts = [p.strip() for p in TITLE_METADATA_SPLIT_RE.split(raw) if p.strip()]
    role = parts[0] if parts else raw
    excluded = parts[1:]
    role = re.sub(r"\s+0\s*(?:to|-|–)\s*\d+\s*years?\b.*$", "", role, flags=re.I).strip()
    return role, excluded

# Aliases are only used when the underlying concept is already evidenced by the
# master resume/profile. They never create unsupported experience.
ALIASES: dict[str, list[str]] = {
    "retrieval augmented generation": ["rag", "retrieval-augmented generation"],
    "rag pipelines": ["rag", "retrieval augmented generation", "retrieval-augmented generation"],
    "retrieval-augmented generation": ["rag", "retrieval augmented generation"],
    "large language model": ["llm", "llms", "large language models"],
    "large language models": ["llm", "llms", "large language model"],
    "artificial intelligence": ["ai"],
    "aiml": ["ai", "ml", "machine learning"],
    "generative artificial intelligence": ["generative ai"],
    "application programming interface": ["api", "apis", "rest api", "rest apis"],
    "vector database": ["vector databases", "faiss", "chromadb"],
    "vector databases": ["vector database", "faiss", "chromadb"],
    "google gemini": ["gemini api", "google gemini api"],
    "machine learning": ["ml", "machine learning"],
    "natural language processing": ["nlp"],
    "browser automation": ["playwright", "browser automation", "web automation"],
    "chrome devtools protocol": ["cdp", "chrome devtools protocol"],
    "llm integration": ["llm", "llms"],
    "agentic ai workflows": ["agentic ai", "ai agents"],
    "agentic ai systems": ["agentic ai", "ai agents"],
    "vector dbs": ["vector databases", "vector database"],
    "vector db": ["vector database", "vector databases"],
    "vector search": ["faiss", "semantic retrieval", "vector database", "vector databases"],
    "llm-based": ["llm", "llms", "large language model", "large language models"],
    "llm based": ["llm", "llms", "large language model", "large language models"],
    "transformer-based models": ["sentence transformers", "transformers", "transformer models"],
    "continuous integration": ["ci"],
    "continuous deployment": ["cd"],
}

CATEGORY_HINTS = {
    "Generative AI & Agents": (
        "ai", "llm", "language model", "rag", "retrieval", "prompt", "agent",
        "generative", "nlp", "embedding", "vector", "langchain", "langgraph",
        "gemini", "ollama"
    ),
    "ML & Deep Learning": (
        "machine learning", "deep learning", "tensorflow", "pytorch", "sklearn",
        "scikit", "statistical", "anomaly", "classification", "regression", "model"
    ),
    "Programming & Data Science": (
        "python", "pandas", "numpy", "matplotlib", "flask", "fastapi", "rest",
        "api", "javascript", "data science", "data analytics", "sql", "analytics"
    ),
    "Databases & SQL": (
        "sql", "mysql", "postgres", "database", "db", "query", "queries", "join",
        "aggregation"
    ),
    "Browser & Workflow Automation": (
        "browser", "playwright", "cdp", "automation", "workflow", "webhook", "n8n",
        "selenium"
    ),
    "Cloud": ("aws", "ec2", "s3", "iam", "rds", "azure", "gcp", "cloud"),
    "Version Control & DevOps": ("git", "github", "ci", "cd", "devops", "docker"),
    "Soft Skills": (
        "communication", "documentation", "analytical", "problem solving", "adaptability",
        "attention", "critical thinking", "time management", "collaboration"
    ),
}

VERB_REPLACEMENTS = {
    "built": ["Developed", "Engineered", "Constructed"],
    "implemented": ["Integrated", "Automated", "Applied"],
    "added": ["Introduced", "Extended", "Integrated"],
    "created": ["Designed", "Constructed", "Produced"],
    "developed": ["Engineered", "Implemented", "Designed"],
    "designed": ["Engineered", "Developed", "Constructed"],
    "engineered": ["Developed", "Implemented", "Designed"],
    "evaluated": ["Validated", "Measured", "Assessed"],
    "achieved": ["Recorded", "Reached", "Delivered"],
    "automated": ["Orchestrated", "Streamlined", "Implemented"],
    "used": ["Applied", "Leveraged", "Integrated"],
}

# These templates are only used when the project block/profile already proves
# the technology. They turn a demonstrated skill into a concrete implementation
# phrase instead of dumping it into a bullet as a keyword list.
PROJECT_INSERTIONS = {
    "python": "using Python",
    "langchain": "using LangChain",
    "faiss": "with FAISS retrieval",
    "chromadb": "with ChromaDB retrieval",
    "sentence transformers": "with Sentence Transformers embeddings",
    "gemini api": "through the Gemini API",
    "google gemini api": "through the Google Gemini API",
    "fastapi": "through FastAPI",
    "playwright": "with Playwright",
    "chrome devtools protocol": "through Chrome DevTools Protocol (CDP)",
    "cdp": "through Chrome DevTools Protocol (CDP)",
    "browser automation": "with browser automation",
    "rest apis": "through REST APIs",
    "rest api": "through REST APIs",
    "mysql": "using MySQL",
    "sql": "using SQL",
    "pytorch": "with PyTorch",
    "tensorflow": "with TensorFlow",
    "scikit-learn": "with Scikit-learn",
    "pandas": "with Pandas",
    "numpy": "with NumPy",
    "aws": "on AWS",
    "n8n": "with n8n",
    "llms": "with large language models (LLMs)",
    "llm": "with large language models (LLMs)",
    "llm integration": "with LLM integration",
    "agentic ai workflows": "with agentic AI workflows",
    "agentic ai systems": "with agentic AI workflows",
    "vector dbs": "with vector databases",
    "vector db": "with vector databases",
    "rag": "using retrieval-augmented generation (RAG)",
    "retrieval augmented generation": "using retrieval-augmented generation (RAG)",
    "retrieval-augmented generation": "using retrieval-augmented generation (RAG)",
}


def _load_resume_content_bank(base_dir: Path) -> dict:
    """Load source-verified resume content options without altering the master resume."""
    candidate = base_dir / "resume_content_bank.json"
    if not candidate.exists():
        return {}
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _rank_content_bank_options(bank: dict, jd_text: str, title: str = "") -> list[dict]:
    """Rank source-verified content options by literal JD overlap.

    This is advisory only: it never changes the master resume by itself.
    """
    jd = norm(f"{title} {jd_text}")
    if not jd:
        return []
    scored: list[tuple[int, int, dict]] = []

    for project in bank.get("project_options", []) or []:
        signals = [project.get("title", ""), *(project.get("keywords", []) or []), *(project.get("tech_stack", []) or []), *(project.get("tags", []) or [])]
        hits = [sig for sig in signals if sig and _phrase_or_term_matches(sig, jd)]
        score = len({norm(x) for x in hits})
        if score:
            scored.append((score, 3, {
                "type": "project",
                "id": project.get("id"),
                "title": project.get("title"),
                "source": project.get("source"),
                "matched_signals": list(dict.fromkeys(hits))[:12],
                "bullet_options": project.get("bullets", []),
                "tech_stack": project.get("tech_stack", []),
            }))

    for group in bank.get("skill_options", []) or []:
        items = group.get("items", []) or []
        hits = [item for item in items if _phrase_or_term_matches(item, jd)]
        if hits:
            scored.append((len(hits), 2, {
                "type": "skill_set",
                "id": group.get("id"),
                "title": group.get("label"),
                "source": ",".join(group.get("sources", [])),
                "matched_signals": hits[:12],
                "items": items,
            }))

    for summary in bank.get("professional_summary_options", []) or []:
        tags = summary.get("tags", []) or []
        hits = [tag for tag in tags if _phrase_or_term_matches(tag, jd)]
        if hits:
            scored.append((len(hits), 1, {
                "type": "summary",
                "id": summary.get("id"),
                "title": "Professional Summary",
                "source": summary.get("source"),
                "matched_signals": hits,
                "text": summary.get("text", ""),
            }))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [item for _, _, item in scored[:12]]


SUMMARY_SKIPWORDS = {
    "experience", "experiences", "work", "working", "works", "role", "roles",
    "engineer", "engineers", "engineering", "candidate", "candidates", "team",
    "teams", "company", "companies", "business", "businesses", "skills", "skill",
    "ability", "abilities", "knowledge", "required", "requirements", "responsibilities",
    "responsibility", "preferred", "strong", "good", "excellent", "communication",
    "collaboration", "collaborative", "proactive", "dynamic", "environment", "development",
    "develop", "developing", "support", "supports", "supporting", "design", "designing",
}

SUMMARY_CATEGORY_HINTS = {
    "Generative AI & Agents": CATEGORY_HINTS["Generative AI & Agents"],
    "ML & Deep Learning": CATEGORY_HINTS["ML & Deep Learning"],
    "Programming & Data Science": CATEGORY_HINTS["Programming & Data Science"],
    "Databases & SQL": CATEGORY_HINTS["Databases & SQL"],
    "Browser & Workflow Automation": CATEGORY_HINTS["Browser & Workflow Automation"],
    "Cloud": CATEGORY_HINTS["Cloud"],
}


def _summary_keyword_is_concrete(keyword: str) -> bool:
    n = norm(keyword)
    if not n or n in SUMMARY_SKIPWORDS:
        return False
    if len(n) < 3 or re.fullmatch(r"[0-9 .%+/-]+", n):
        return False
    if len(n.split()) > 4:
        return False
    return any(any(h in n for h in hints) for hints in SUMMARY_CATEGORY_HINTS.values())


def _select_summary_keywords(report_rows: list[dict], master: str, profile: dict, base_text: str, limit: int = 5) -> list[str]:
    candidates: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for pos, row in enumerate(report_rows):
        kw = str(row.get("keyword", "")).strip()
        if not _summary_keyword_is_concrete(kw):
            continue
        nk = norm(kw)
        if nk in seen:
            continue
        supported, _ = _supported_evidence(kw, master, profile)
        applicable = _applicable_keyword(kw, profile)
        if not (supported and applicable):
            continue
        score = 0
        if exact_occurrence(master, kw):
            score += 2
        if exact_occurrence(base_text, kw):
            score += 4
        if len(kw.split()) > 1:
            score += 2
        if nk in ALIASES:
            score += 1
        candidates.append((score, -pos, kw))
        seen.add(nk)
    candidates.sort(reverse=True)
    return [kw for _, _, kw in candidates[:limit]]


def _summary_metric_phrase(project: dict | None) -> str:
    if not project:
        return ""
    metrics = [str(x).strip() for x in (project.get("metrics", []) or []) if str(x).strip()]
    if not metrics:
        return ""
    preferred = sorted(
        metrics,
        key=lambda m: (
            3 if "%" in m else 0,
            2 if any(x in m.lower() for x in ("accuracy", "iou", "f1", "applications", "records", "skus")) else 0,
            len(m),
        ),
        reverse=True,
    )[0]
    n = norm(preferred)
    if "applications" in n:
        return f"Processed {preferred} through autonomous application workflows."
    if "accuracy" in n:
        return f"Validated intent classification at {preferred.replace('accuracy', '').strip()} accuracy on adversarial testing."
    if n.startswith("iou"):
        return f"Reached {preferred} on held-out image segmentation."
    if "f1" in n:
        return f"Reached {preferred} on held-out model evaluation."
    if "pixel accuracy" in n:
        return f"Recorded {preferred} on held-out image segmentation."
    if "null" in n or "→" in preferred or "->" in preferred:
        return f"Detected a {preferred} shift in customer-email nulls across 257 records."
    if "similarity threshold" in n or n == "0.35":
        return f"Applied a {preferred} for low-confidence retrieval handling."
    if "records" in n:
        return f"Flagged {preferred} during statistical data-quality validation."
    if "skus" in n:
        return f"Analyzed {preferred} in inventory decision workflows."
    return f"Measured {preferred} in source-verified project evaluation."


def _select_summary_project(bank: dict, jd_text: str) -> dict | None:
    jd = norm(jd_text)
    ranked: list[tuple[int, dict]] = []
    for project in bank.get("project_options", []) or []:
        signals = [project.get("title", ""), *(project.get("keywords", []) or []), *(project.get("tech_stack", []) or []), *(project.get("tags", []) or [])]
        hits = sum(1 for sig in signals if sig and _phrase_or_term_matches(sig, jd))
        if hits:
            ranked.append((hits, project))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1] if ranked else None


def _tailor_professional_summary(template: str, bank: dict, report_rows: list[dict], master: str, profile: dict, jd_text: str) -> tuple[str, dict]:
    """Preserve the master outcome and add only concise, project-grounded JD language."""
    a = template.index(r"\section{Professional Summary}") + len(r"\section{Professional Summary}")
    b = template.index(r"\section{Core Competencies / Skills}", a)
    section = template[a:b]
    master_match = re.search(r"\\begin\{onecolentry\}\s*(.*?)\s*\\end\{onecolentry}", section, re.DOTALL)
    master_summary = (master_match.group(1).replace(r"\%", "%").replace(r"\&", "&") if master_match else "")
    if not master_summary:
        return template, {"changed": False, "reason": "master summary unavailable", "inserted_keywords": []}
    supported = []
    for row in report_rows:
        kw = str(row.get("keyword", "")).strip()
        if row.get("match_type") == "exact":
            continue
        evidence, ok = _supported_evidence(kw, master, profile)
        if ok and evidence and _applicable_keyword(kw, profile):
            supported.append(kw)
    norms = {norm(x): x for x in supported}
    sentence = ""
    inserted: list[str] = []
    if {"rag", "llm", "llm integration", "retrieval augmented generation", "retrieval-augmented generation"}.intersection(norms) or "large language model" in norms or "llms" in norms:
        if "agentic ai" in norms or "agentic ai workflows" in norms or "ai agents" in norms:
            sentence = "Recent work applies RAG pipelines, LLM integration, and agentic AI workflows to grounded document Q&A and automated decision systems."
            inserted = [x for x in supported if norm(x) in {"rag", "retrieval augmented generation", "retrieval-augmented generation", "llm", "llms", "large language model", "agentic ai", "agentic ai workflows", "ai agents"}]
        else:
            sentence = "Recent work applies RAG pipelines and LLM integration to grounded document Q&A and AI agents."
            inserted = [x for x in supported if norm(x) in {"rag", "retrieval augmented generation", "retrieval-augmented generation", "llm", "llms", "large language model"}]
    elif "agentic ai" in norms or "ai agents" in norms or "agents" in norms:
        sentence = "Recent work includes agentic AI workflows for automated application and support decision systems."
        inserted = [x for x in supported if norm(x) in {"agentic ai", "ai agents", "agents"}]
    elif "vector database" in norms or "vector dbs" in norms or "vector databases" in norms or "vector search" in norms:
        sentence = "Recent work includes vector search and retrieval pipelines for document-based AI systems."
        inserted = [x for x in supported if norm(x) in {"vector database", "vector dbs", "vector databases", "vector search"}]
    summary_text = master_summary.rstrip(".") + "."
    if sentence and norm(sentence) not in norm(summary_text):
        summary_text += " " + sentence
    words = re.findall(r"\b[\w+#./%→-]+\b", summary_text)
    new_section = (
        "\n\n        \\begin{onecolentry}\n"
        + "      " + latex_escape(summary_text) + "\n"
        + "        \\end{onecolentry}\n\n"
        + "   \\vspace{0.02 cm}\n   \n\n"
    )

    details = {
        "changed": bool(sentence),
        "source_option": "master_resume_preserved",
        "matched_summary_tags": [],
        "inserted_keywords": list(dict.fromkeys(inserted)),
        "metric_project": "",
        "metric_sentence": "",
        "master_outcome_preserved": True,
        "word_count": len(words),
        "technical_focus_append_removed": True,
    }
    return template[:a] + new_section + template[b:], details

def norm(value: str) -> str:
    value = str(value or "")
    value = value.replace(r"\&", "&")
    value = value.replace("\u2013", "-").replace("\u2014", "-")
    value = value.lower()
    value = re.sub(r"[^a-z0-9+#.&/-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def latex_escape(value: str) -> str:
    value = str(value or "")
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
    }
    return "".join(replacements.get(ch, ch) for ch in value)


def token_forms(term: str) -> set[str]:
    n = norm(term)
    forms = {n}
    if re.fullmatch(r"[a-z0-9+#.&/-]+", n):
        if n.endswith("ies") and len(n) > 4:
            forms.add(n[:-3] + "y")
        elif n.endswith("s") and not n.endswith("ss") and len(n) > 3:
            forms.add(n[:-1])
        elif not n.endswith("s") and len(n) > 3:
            forms.add(n + "s")
    return {x for x in forms if x}


def exact_occurrence(haystack: str, term: str) -> str | None:
    if not term.strip():
        return None
    pattern = re.escape(term.strip())
    m = re.search(pattern, haystack, flags=re.I)
    return m.group(0) if m else None


def _word_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9+#./&'\-]*", text)


def _literal_pass(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for token in _word_tokens(text):
        clean = token.strip(".,;:!?()[]{}\"")
        n = norm(clean)
        if not n or n in GRAMMATICAL_STOPWORDS or len(n) < 2:
            continue
        if re.fullmatch(r"\d+", n):
            continue
        if n not in seen:
            out.append(clean)
            seen.add(n)
    return out


def _phrase_pass(text: str) -> list[str]:
    """Extract only explicit, meaningful JD phrases; never create sliding windows."""
    raw = _normalize_jd_delimiters(str(text or ""))
    normalized = norm(raw)
    out: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = re.sub(r"\s+", " ", value.strip(" .,;:!?()[]{}\""))
        n = norm(value)
        if not n or n in seen or n in PHRASE_GENERIC:
            return
        seen.add(n)
        out.append(value)

    for seed in PHRASE_SEEDS:
        if re.search(rf"(?<![a-z0-9]){re.escape(norm(seed))}(?![a-z0-9])", normalized):
            add(seed)
    return out


def extract_keyword_inventory(jd_text: str, title: str = "") -> dict:
    """Extract a two-pass literal JD inventory while excluding job-board metadata."""
    role_title, excluded_metadata = _role_title_and_excluded_metadata(title)
    body = _normalize_jd_delimiters(jd_text).strip()
    source = body
    pass1 = _literal_pass(source)
    normalized_source = re.sub(r"\s+", " ", source)
    pass1b = _literal_pass(normalized_source)
    phrases = _phrase_pass(body)

    phrase_component_tokens: set[str] = set()
    for phrase in phrases:
        phrase_component_tokens.update(tok for tok in norm(phrase).split() if tok)

    singles: list[str] = []
    seen_singles: set[str] = set()
    for item in [*pass1, *pass1b]:
        n = norm(item)
        if (not n or n in MALFORMED_TITLE_FRAGMENTS or n in seen_singles
                or n in {"db", "dbs", "and/or"} or n in phrase_component_tokens):
            continue
        singles.append(item)
        seen_singles.add(n)

    merged_phrases: list[str] = []
    seen_phrases: set[str] = set()
    for item in phrases:
        n = norm(item)
        if n and n not in seen_phrases and n not in seen_singles:
            merged_phrases.append(item)
            seen_phrases.add(n)
    return {
        "title": title,
        "role_title": role_title,
        "excluded_title_metadata": excluded_metadata,
        "single_word_keywords": singles,
        "phrase_keywords": merged_phrases,
        "all_literals": singles + merged_phrases,
        "second_pass_verified": True,
    }

def _phrase_or_term_matches(term: str, resume_text: str, _seen: set[str] | None = None) -> str | None:
    rn = norm(resume_text)
    current = norm(term)
    seen = set() if _seen is None else set(_seen)
    if not current or current in seen:
        return None
    seen.add(current)

    for candidate in token_forms(current):
        if " " in candidate or any(ch in candidate for ch in "+#.&/-"):
            if re.search(re.escape(candidate), rn, re.I):
                return exact_occurrence(resume_text, term) or exact_occurrence(resume_text, candidate) or candidate
        else:
            if re.search(rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])", rn, re.I):
                return exact_occurrence(resume_text, candidate) or candidate

    for alias in ALIASES.get(current, []):
        hit = _phrase_or_term_matches(alias, resume_text, seen)
        if hit:
            return hit
    return None


def _supported_evidence(term: str, template: str, profile: dict) -> tuple[bool, str]:
    hit = _phrase_or_term_matches(term, template)
    if hit:
        return True, f"master resume: {hit}"
    for skill in profile.get("skills", []) or []:
        if _phrase_or_term_matches(term, str(skill)):
            return True, f"profile skill: {skill}"
    for project in profile.get("projects", []) or []:
        evidence = f"{project.get('title','')} {project.get('details','')}"
        if _phrase_or_term_matches(term, evidence):
            return True, f"profile project evidence: {project.get('title','')}"
    return False, ""


def _project_evidence(project: dict) -> str:
    tech = " ".join(str(x) for x in (project.get("tech_stack", []) or []))
    keywords = " ".join(str(x) for x in (project.get("keywords", []) or []))
    return f"{project.get('title','')} {project.get('details','')} {tech} {keywords}"


def _project_supports(term: str, project: dict) -> bool:
    return bool(_phrase_or_term_matches(term, _project_evidence(project)))



def _content_bank_project(bank: dict, title: str) -> dict | None:
    nt = norm(title)
    for project in bank.get("project_options", []) or []:
        if norm(project.get("title", "")) == nt:
            return project
        # Common source-title aliases for projects whose master title is shortened.
        aliases = {
            "ai data quality & root-cause analyst": "data quality & root-cause analyst",
            "ai-powered autonomous job application agent": "ai-powered autonomous job application agent",
            "customer support triage & resolution agent": "customer support triage & resolution agent",
            "dronevision – drone-based construction monitoring": "dronevision – drone-based construction monitoring",
        }
        if aliases.get(nt) == norm(project.get("title", "")):
            return project
    return None


def _bullet_word_count_plain(text: str) -> int:
    return len(re.findall(r"\b[\w+#./-]+\b", _bullet_plain(text)))


def _strong_bullet_options(project: dict | None) -> list[str]:
    if not project:
        return []
    values = project.get("strong_bullets", []) or []
    return [str(x).strip() for x in values if str(x).strip()]


def _bullet_metric_tokens(text: str) -> list[str]:
    plain = _bullet_plain(text).replace("\\%", "%")
    return _extract_metrics(plain)


def _apply_stronger_project_bullets(block: str, project: dict | None, jd_text: str) -> tuple[str, list[dict]]:
    """Replace master bullets only when a verified option is materially better for this JD."""
    options = _strong_bullet_options(project)
    if not options:
        return block, []
    current = list(_bullet_matches(block))
    if not current:
        return block, []
    jd = norm(jd_text)
    selected: list[str] = []
    changes: list[dict] = []
    used: set[str] = set()
    def score(text: str) -> int:
        terms = [t for t in re.split(r"[^a-z0-9+#./%-]+", norm(text)) if len(t) >= 3]
        return sum(1 for t in set(terms) if t and t in jd)
    for idx, (raw, _plain, _count) in enumerate(current):
        current_plain = _bullet_plain(raw)
        current_score = score(current_plain)
        current_metrics = [m.lower() for m in _bullet_metric_tokens(current_plain)]
        candidates: list[tuple[int, str]] = []
        for opt in options:
            if opt in used or _bullet_word_count_plain(opt) > 25:
                continue
            opt_score = score(opt)
            if opt_score < current_score + 2:
                continue
            opt_plain = _bullet_plain(opt)
            if any(metric not in opt_plain.lower() for metric in current_metrics):
                continue
            new_terms = set(re.split(r"[^a-z0-9+#./%-]+", norm(opt))) - set(re.split(r"[^a-z0-9+#./%-]+", norm(current_plain)))
            if not any(t and t in jd and len(t) >= 4 for t in new_terms):
                continue
            candidates.append((opt_score, opt))
        if not candidates:
            selected.append(current_plain.rstrip(".") + ".")
            continue
        candidates.sort(key=lambda x: (x[0], _bullet_has_number(x[1])), reverse=True)
        chosen = candidates[0][1].rstrip(".") + "."
        selected.append(chosen)
        used.add(candidates[0][1])
        changes.append({
            "project": _project_title(block),
            "bullet_index": idx + 1,
            "reason": "strictly_better_jd_overlap",
            "previous_score": current_score,
            "new_score": candidates[0][0],
            "new_word_count": _bullet_word_count_plain(chosen),
        })
    if not changes:
        return block, []
    candidate_block = block
    for i, text in enumerate(selected):
        if norm(_bullet_plain(current[i][0])) != norm(text):
            candidate_block = _replace_bullet(candidate_block, i, latex_escape(text))
    return candidate_block, changes

def _resume_cv_check_rows(report_rows: list[dict]) -> dict:
    total=len(report_rows)
    exact=sum(1 for x in report_rows if x.get("match_type") == "exact")
    near=sum(1 for x in report_rows if x.get("match_type") == "near")
    missing=sum(1 for x in report_rows if not x.get("in_resume"))
    return {
        "total_keywords_checked": total,
        "exact_matches": exact,
        "near_matches": near,
        "missing_matches": missing,
        "coverage_percent": round(((exact+near)/total)*100, 1) if total else 0.0,
        "status": "PASS" if total and missing == 0 else ("PARTIAL" if total else "NO_DATA"),
    }


def _bullet_style_check(template: str) -> dict:
    issues=[]
    for block in _project_blocks(template):
        title=_project_title(block)
        for idx,(raw,plain,count) in enumerate(_bullet_matches(block)):
            p=_bullet_plain(raw).strip()
            if p and not p[0].isupper():
                issues.append({"project":title,"bullet_index":idx+1,"issue":"does_not_start_with_capital"})
            if p and not p.endswith('.'):
                issues.append({"project":title,"bullet_index":idx+1,"issue":"does_not_end_with_period"})
            if count > 25:
                issues.append({"project":title,"bullet_index":idx+1,"issue":"over_25_words","count":count})
    return {"pass": not issues, "issues": issues}


def _project_blocks(template: str) -> list[str]:
    a = template.index(r"\section{Projects/Experience}") + len(r"\section{Projects/Experience}")
    b = template.index(r"\section{Education}", a)
    body = template[a:b]
    parts = re.split(r"(?=^[ \t]*\\begin\{twocolentry\}\{)", body, flags=re.MULTILINE)
    return [p for p in parts[1:] if r"\begin{twocolentry}" in p]


def _project_title(block: str) -> str:
    values = re.findall(r"\\textbf\{([^{}]+)\}", block)
    for value in values:
        value = value.replace(r"\&", "&").strip()
        if not re.fullmatch(r"\d{4}(?:\s*[--\u2013-]\s*\d{4})?", value):
            return value
    return values[0].replace(r"\&", "&").strip() if values else ""


def _bullet_matches(block: str) -> list[tuple[str, str, int]]:
    out = []
    for m in re.finditer(r"\\item\s+(.+?)(?=\n\s*\\item|\n\s*\\end\{highlights\})", block, re.DOTALL):
        raw = m.group(1).strip()
        plain = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})?", " ", raw)
        words = re.findall(r"\b[\w+#./-]+\b", plain)
        out.append((raw, plain, len(words)))
    return out


def _all_bullet_word_counts(template: str) -> list[int]:
    counts = []
    for m in re.finditer(r"\\item\s+(.+?)(?=\n\s*\\item|\n\s*\\end\{highlights\})", template, re.DOTALL):
        plain = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})?", " ", m.group(1))
        counts.append(len(re.findall(r"\b[\w+#./-]+\b", plain)))
    return counts


def _replace_bullet(block: str, index: int, new_text: str) -> str:
    matches = list(re.finditer(r"(\\item\s+)(.+?)(?=\n\s*\\item|\n\s*\\end\{highlights\})", block, re.DOTALL))
    if index >= len(matches):
        return block
    m = matches[index]
    return block[:m.start(2)] + new_text + block[m.end(2):]


def _bullet_plain(text: str) -> str:
    text = re.sub(r"\\textbf\{([^{}]+)\}", r"\1", text)
    text = re.sub(r"\\href\{[^{}]*\}\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})?", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _bullet_has_number(text: str) -> bool:
    return bool(re.search(r"\d", _bullet_plain(text)))


def _skill_like(term: str) -> bool:
    n = norm(term)
    signals = (
        "ai", "ml", "llm", "rag", "sql", "python", "java", "c++", "aws", "api",
        "lang", "faiss", "chroma", "gemini", "ollama", "playwright", "cdp",
        "tensorflow", "pytorch", "fastapi", "flask", "pandas", "numpy", "mysql",
        "github", "git", "docker", "n8n", "webhook", "automation", "nlp", "kpi",
        "excel", "power bi", "documentation", "mathematics"
    )
    return any(x in n for x in signals)


def _applicable_keyword(term: str, profile: dict) -> bool:
    n = norm(term)
    known = {norm(s) for s in (profile.get("skills", []) or [])}
    if n in known or n in ALIASES:
        return True
    for skill in known:
        if n in token_forms(skill) or skill in token_forms(n):
            return True
    return False


def _project_keyword_support(term: str, block: str, project: dict | None) -> bool:
    n = norm(term)
    if n in ROLE_TITLE_ONLY_TERMS:
        return False
    if n == "agentic ai workflows":
        block_norm = norm(block)
        if "autonomous" in block_norm and "agent" in block_norm:
            return True
    if _phrase_or_term_matches(term, block):
        return True
    return bool(project and _project_supports(term, project))


def _existing_skill_category_line(template: str, keyword: str) -> tuple[int, int, str] | None:
    category = None
    n = norm(keyword)
    for candidate, hints in CATEGORY_HINTS.items():
        if any(h in n for h in hints):
            category = candidate
            break
    if not category:
        return None
    category_latex = category.replace("&", r"\&")
    pattern = rf"(?P<prefix>\\textbf\{{{re.escape(category_latex)}:\}}\s*)(?P<body>[^\n]+)"
    m = re.search(pattern, template)
    if not m:
        return None
    return m.start("body"), m.end("body"), m.group("body")


ROLE_TITLE_ONLY_TERMS = {"aiml"}

CANONICAL_SKILL_LABELS = {
    "vector dbs": "Vector DBs",
    "vector db": "Vector DB",
    "vector search": "Vector Search",
    "retrieval augmented generation": "Retrieval-Augmented Generation (RAG)",
    "retrieval-augmented generation": "Retrieval-Augmented Generation (RAG)",
    "llm integration": "LLM Integration",
    "agentic ai workflows": "Agentic AI Workflows",
    "transformer-based models": "Transformer-Based Models",
}

def _skill_equivalent_present(body: str, keyword: str) -> bool:
    n = norm(keyword)
    if exact_occurrence(body, keyword):
        return True
    for alias in ALIASES.get(n, []):
        if exact_occurrence(body, alias):
            return True
    return False

def _skill_word_count(text: str) -> int:
    return len(re.findall(r"\b[\w+#./&-]+\b", re.sub(r"\s+", " ", text)))

def _insert_skill_keyword(template: str, keyword: str) -> tuple[str, bool]:
    target = _existing_skill_category_line(template, keyword)
    if not target:
        return template, False
    start, end, body = target
    n = norm(keyword)
    if n == "vector dbs" and "Vector Databases" in body and "Vector DBs" not in body:
        new_body = body.replace("Vector Databases", "Vector Databases / Vector DBs", 1)
        if _skill_word_count(new_body) <= 25:
            return template[:start] + new_body + template[end:], True
        return template, False
    if n not in {"llm integration", "vector search"} and _skill_equivalent_present(body, keyword):
        return template, False
    display = CANONICAL_SKILL_LABELS.get(n, keyword)
    addition = latex_escape(display)
    separator = "" if body.endswith(",") else ","
    new_body = body.rstrip() + separator + " " + addition
    if _skill_word_count(new_body) > 25:
        return template, False
    return template[:start] + new_body + template[end:], True


def _phrase_expand_in_bullet(bullet: str, keyword: str) -> tuple[str, bool]:
    n = norm(keyword)
    aliases = ALIASES.get(n, [])
    if not aliases:
        return bullet, False
    for alias in aliases:
        hit = exact_occurrence(bullet, alias)
        if not hit:
            continue
        replacement = f"{latex_escape(keyword)} ({hit})"
        candidate = re.sub(re.escape(hit), replacement, bullet, count=1, flags=re.I)
        if _bullet_word_count_plain(candidate) > 25:
            return bullet, False
        return candidate, True
    return bullet, False


def _rewrite_supported_project_bullet(block: str, keyword: str, project: dict | None) -> tuple[str, bool, dict | None]:
    n = norm(keyword)
    if not project:
        return block, False, None
    if n in {"retrieval augmented generation", "retrieval-augmented generation", "rag pipelines", "rag"}:
        if not _phrase_or_term_matches("rag", block):
            return block, False, None
        for idx, (raw, plain, count) in enumerate(_bullet_matches(block)):
            low = plain.lower()
            if "retrieves knowledge" in low and "customer" in low:
                if "retrieval-augmented generation" in low or "rag pipeline" in low:
                    return block, False, None
                if norm(keyword) == "rag pipelines":
                    candidate = (
                        "Developed an AI support agent with RAG pipelines for knowledge retrieval, "
                        "customer-data checks, and safe-resolution gating."
                    )
                else:
                    display_phrase = "Retrieval-Augmented Generation" if "-" in str(keyword) else "Retrieval Augmented Generation"
                    candidate = (
                        f"Developed an AI support agent using {display_phrase} (RAG) for "
                        "knowledge retrieval, customer-data checks, and safe-resolution gating."
                    )
                if _bullet_word_count_plain(candidate) > 25:
                    return block, False, None
                return _replace_bullet(block, idx, latex_escape(candidate)), True, {
                    "keyword": keyword,
                    "bullet_index": idx + 1,
                    "reason": "rewrote supported RAG implementation wording",
                    "new_word_count": _bullet_word_count_plain(candidate),
                }
    if n in {"llm integration", "llm-based", "llm based"}:
        if not _phrase_or_term_matches("llm", block) and not _phrase_or_term_matches("gemini", block):
            return block, False, None
        for idx, (raw, plain, count) in enumerate(_bullet_matches(block)):
            low = plain.lower()
            if "gemini reasoning" in low and "ollama fallback" in low or ("gemini llm integration" in low and "ollama fallback" in low):
                candidate = (
                    "Implemented deterministic Q&A routing with profile facts, Gemini LLM integration for LLM-based reasoning, "
                    "Ollama fallback, and answer verification."
                )
                if _bullet_word_count_plain(candidate) > 25 or norm(_bullet_plain(raw)) == norm(candidate):
                    return block, False, None
                return _replace_bullet(block, idx, latex_escape(candidate)), True, {
                    "keyword": keyword,
                    "bullet_index": idx + 1,
                    "reason": "rewrote supported LLM integration wording",
                    "new_word_count": _bullet_word_count_plain(candidate),
                }
    if n == "agentic ai workflows":
        block_norm = norm(block)
        has_autonomous_agent = "autonomous" in block_norm and "agent" in block_norm
        if not (has_autonomous_agent or _phrase_or_term_matches("agentic", block)):
            return block, False, None
        for idx, (raw, plain, count) in enumerate(_bullet_matches(block)):
            low = plain.lower()
            if "automation with playwright" in low and "eligibility gates" in low:
                candidate = (
                    "Engineered Naukri, Indeed, and LinkedIn automation with agentic AI workflows, "
                    "Playwright, CDP, JD matching, and eligibility gates."
                )
                if _bullet_word_count_plain(candidate) > 25:
                    return block, False, None
                return _replace_bullet(block, idx, latex_escape(candidate)), True, {
                    "keyword": keyword,
                    "bullet_index": idx + 1,
                    "reason": "rewrote supported agentic workflow wording",
                    "new_word_count": _bullet_word_count_plain(candidate),
                }
    return block, False, None

def _insert_supported_keyword_into_bullet(block: str, keyword: str, project: dict | None) -> tuple[str, bool, dict | None]:
    # If the term already exists somewhere in the project block, no insertion is needed.
    if exact_occurrence(block, keyword):
        return block, False, None

    n = norm(keyword)
    insertion = PROJECT_INSERTIONS.get(n)
    if not insertion:
        # Try a known alias to reach a canonical insertion phrase.
        for alias in ALIASES.get(n, []):
            insertion = PROJECT_INSERTIONS.get(norm(alias))
            if insertion:
                break
    if not insertion:
        return block, False, None
    if project and not _project_supports(keyword, project):
        # Do not assert the term merely because it is a global profile skill.
        return block, False, None
    if not project and not _phrase_or_term_matches(keyword, block):
        return block, False, None

    bullets = list(_bullet_matches(block))
    best_index = None
    best_score = -1
    for idx, (raw, plain, count) in enumerate(bullets):
        if count > 21:
            continue
        score = 0
        if any(v in plain.lower() for v in ("implemented", "developed", "built", "engineered", "created", "added", "integrated")):
            score += 2
        if count < 19:
            score += 1
        if _bullet_has_number(raw):
            score += 1
        if score > best_score:
            best_index = idx
            best_score = score
    if best_index is None:
        return block, False, None

    raw, plain, count = bullets[best_index]
    # Avoid awkward duplicate "using ... using ..." patterns.
    if insertion.lower() in plain.lower():
        return block, False, None
    suffix = f" {insertion}."
    stripped = raw.rstrip()
    punctuation = stripped[-1:] if stripped else ""
    if punctuation in ".;!":
        stripped = stripped[:-1]
        suffix = f" {insertion}{punctuation}"
    candidate = stripped + suffix
    candidate_count = len(re.findall(r"\b[\w+#./-]+\b", _bullet_plain(candidate)))
    if candidate_count > 25:
        return block, False, None
    return _replace_bullet(block, best_index, candidate), True, {
        "keyword": keyword,
        "bullet_index": best_index + 1,
        "reason": "supported project evidence",
        "new_word_count": candidate_count,
    }


OVERLONG_BULLET_REWRITES = {
    "Integrated the Gemini API with FastAPI and Streamlit to turn validated analytical findings into grounded explanations and decision support; simulated testing showed ~30% lower stockout risk while processing 1,000 SKUs in ~12 seconds.":
        "Integrated Gemini API, FastAPI, and Streamlit for grounded explanations; simulated testing showed ~30% lower stockout risk while processing 1,000 SKUs in ~12 seconds.",
}

def _compact_overlong_bullets(template: str) -> tuple[str, list[dict]]:
    changes: list[dict] = []
    for block in _project_blocks(template):
        project = _project_title(block)
        updated = block
        for idx, (raw, plain, count) in enumerate(_bullet_matches(block)):
            if count <= 25:
                continue
            original = _bullet_plain(raw)
            replacement = OVERLONG_BULLET_REWRITES.get(original) or OVERLONG_BULLET_REWRITES.get(original.replace(r"\%", "%"))
            if not replacement or _bullet_word_count_plain(replacement) > 25:
                continue
            old_metrics = set(_bullet_metric_tokens(original))
            new_metrics = set(_bullet_metric_tokens(replacement))
            if not old_metrics.issubset(new_metrics):
                continue
            updated = _replace_bullet(updated, idx, latex_escape(replacement))
            changes.append({
                "project": project,
                "bullet_index": idx + 1,
                "keyword": "",
                "change": "format_compaction_preserving_master_metrics",
                "new_word_count": _bullet_word_count_plain(replacement),
            })
    # Rebuild all blocks in the template.
    if not changes:
        return template, []
    a = template.index(r"\section{Projects/Experience}") + len(r"\section{Projects/Experience}")
    b = template.index(r"\section{Education}", a)
    body = template[a:b]
    parts = re.split(r"(?=^[ \t]*\\begin\{twocolentry\}\{)", body, flags=re.MULTILINE)
    if len(parts) < 3:
        return template, changes
    rebuilt = [parts[0]]
    for block in parts[1:]:
        project = _project_title(block)
        current = block
        for idx, (raw, _plain, count) in enumerate(_bullet_matches(block)):
            if count > 25:
                original = _bullet_plain(raw)
                replacement = OVERLONG_BULLET_REWRITES.get(original) or OVERLONG_BULLET_REWRITES.get(original.replace(r"\%", "%"))
                if replacement and _bullet_word_count_plain(replacement) <= 25 and set(_bullet_metric_tokens(original)).issubset(set(_bullet_metric_tokens(replacement))):
                    current = _replace_bullet(current, idx, latex_escape(replacement))
        rebuilt.append(current)
    return template[:a] + rebuilt[0] + "".join(rebuilt[1:]) + template[b:], changes


def _rewrite_repeated_verbs(template: str) -> tuple[str, list[dict], list[dict]]:
    bullet_pattern = re.compile(r"(\\item\s+)([A-Za-z]+)(\b)")
    occurrences = []
    counts = Counter()
    for m in bullet_pattern.finditer(template):
        verb = m.group(2)
        v = verb.lower()
        counts[v] += 1
        occurrences.append((m.start(2), v, verb))

    fixes: list[dict] = []
    flagged: list[dict] = []
    replacements: list[tuple[int, str, str]] = []
    for verb, count in counts.items():
        if count > 2:
            flagged.append({"verb": verb, "count": count})
    for start, v, original in occurrences:
        if counts[v] <= 2 or v not in VERB_REPLACEMENTS:
            continue
        seen_before = sum(1 for s, vv, _ in occurrences if vv == v and s <= start)
        if seen_before <= 2:
            continue
        alternatives = VERB_REPLACEMENTS[v]
        alt = alternatives[(seen_before - 3) % len(alternatives)]
        replacements.append((start, original, alt))
    for start, original, alt in reversed(replacements):
        template = template[:start] + alt + template[start + len(original):]
        fixes.append({"from": original, "to": alt})
    return template, fixes, flagged


def _extract_metrics(text: str) -> list[str]:
    plain = text.replace(r"\%", "%")
    values = []
    seen = set()
    for m in re.finditer(r"\b\d+(?:\.\d+)?%|\b\d[\d,]*(?:\.\d+)?\b", plain):
        value = m.group(0)
        # Dates alone are not treated as impact metrics.
        if re.fullmatch(r"20\d{2}", value):
            continue
        if value not in seen:
            values.append(value)
            seen.add(value)
    return values


GENERIC_JD_GAP_TERMS = {
    "design", "develop", "deploy", "solutions", "leveraging", "architectures", "systems",
    "expertise", "knowledge", "experience", "integrating", "models", "scalable", "environments",
    "implement", "frameworks", "optimize", "strategies", "build", "pipelines",
    "apis", "enterprise", "applications", "workflows", "tool", "function", "calling",
    "vector", "search", "databases", "ensure", "establish", "teams", "deliver", "features",
    "proficiency", "understanding", "concepts", "required", "requirements", "responsibilities",
}

def _classify_gap(keyword: str) -> str:
    n = norm(keyword)
    if not n or n in MALFORMED_TITLE_FRAGMENTS or n in GENERIC_JD_GAP_TERMS:
        return "checker_glitch"
    tool_terms = (
        "python", "matlab", "simulink", "airflow", "kafka", "mongodb", "azure", "aws",
        "openai", "azure openai", "faiss", "chroma", "pinecone", "weaviate", "milvus",
        "pytorch", "tensorflow", "docker", "kubernetes", "github actions", "cicd", "ci/cd",
        "langchain", "langgraph", "fastapi", "playwright", "selenium", "function calling",
        "tool calling", "vector database", "vector db",
    )
    if any(t in n for t in tool_terms) or re.search(r"\b(?:\d+(?:\.\d+)?%|top[- ]?\d+|\d+[kKmM+])\b", n):
        return "authenticity_risk"
    return "real_content_gap"


@dataclass
class TailoringReport:
    authenticity_flags: list[dict]
    keyword_inventory_count: int
    phrase_inventory_count: int
    second_pass_verified: bool
    matched_keywords: list[dict]
    safe_additions: list[dict]
    unsupported_keywords: list[dict]
    added_keywords: list[str]
    rewritten_bullets: list[dict]
    reordered_projects: list[str]
    repeated_verb_fixes: list[dict]
    repeated_verbs_flagged: list[dict]
    quantification_gaps: list[dict]
    analysis_data_repetition_flags: list[dict]
    bullet_word_counts: list[int]
    metrics_preserved: bool
    preserved_metrics: list[str]
    missing_metrics: list[str]
    verification: dict
    content_bank_options: list[dict]
    cv_check: dict
    stronger_bullet_selections: list[dict]
    metric_locks: dict
    bullet_style_check: dict
    summary_tailoring: dict
    gap_classifications: list[dict]
    prompt_spec: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TailoredResume:
    latex: str
    matched_skills: list[str]
    keywords: list[str]
    report: dict


class ATSAuthenticResumeTailor:
    """JD-aware, fact-preserving ATS tailoring.

    The master resume is immutable. Only supported JD language is surfaced, and
    project bullets are changed only when the master/profile provides project-
    level evidence for that technology/concept.
    """

    def __init__(self, profile: dict, master_template_path: str | Path):
        self.profile = profile
        self.master_template_path = Path(master_template_path)
        self.content_bank = _load_resume_content_bank(self.master_template_path.parent.parent)

    def _validate_template(self, text: str) -> None:
        required = (
            r"\documentclass", r"\begin{document}", r"\section{Professional Summary}",
            r"\section{Core Competencies / Skills}", r"\section{Projects/Experience}",
            r"\section{Education}", r"\section{Certifications}", r"\end{document}"
        )
        missing = [x for x in required if x not in text]
        if missing:
            raise ValueError("master resume template missing: " + ", ".join(missing))

    def _authenticity_scan(self, template: str, jd_text: str) -> list[dict]:
        flags: list[dict] = []
        jd_words = norm(jd_text).split()
        jd_ngrams: set[str] = set()
        for n in (8, 7, 6):
            for i in range(len(jd_words) - n + 1):
                phrase = " ".join(jd_words[i:i + n])
                if sum(w not in GRAMMATICAL_STOPWORDS for w in phrase.split()) >= n - 1:
                    jd_ngrams.add(phrase)
        for line in template.splitlines():
            if not line.strip().startswith(r"\item") and "Engineering graduate" not in line:
                continue
            content = _bullet_plain(line)
            cn = norm(content)
            overlap = next((p for p in jd_ngrams if p in cn), None)
            if overlap:
                flags.append({
                    "line": content,
                    "overlap": overlap,
                    "action": "review/rephrase with project-specific wording",
                })
        return flags

    def _match_check(self, keyword_list: Iterable[str], template: str) -> list[dict]:
        out = []
        for kw in keyword_list:
            exact = exact_occurrence(template, kw)
            near = None if exact else _phrase_or_term_matches(kw, template)
            out.append({
                "keyword": kw,
                "in_resume": bool(exact or near),
                "match_type": "exact" if exact else ("near" if near else "none"),
                "exact_wording_used": exact or near or "",
            })
        return out

    def _reorder_skills(self, template: str, matched_keywords: set[str]) -> str:
        a = template.index(r"\section{Core Competencies / Skills}") + len(r"\section{Core Competencies / Skills}")
        b = template.index(r"\section{Projects/Experience}", a)
        body = template[a:b]
        blocks = list(re.finditer(r"\\begin\{onecolentry\}.*?\\end\{onecolentry\}", body, re.DOTALL))
        if not blocks:
            return template
        values = [m.group(0) for m in blocks]
        scored = []
        for i, block in enumerate(values):
            score = sum(1 for kw in matched_keywords if _phrase_or_term_matches(kw, block))
            scored.append((score, -i, i))
        order = [i for _, _, i in sorted(scored, reverse=True)]
        replacement_map = {idx: values[order[pos]] for pos, idx in enumerate(range(len(values)))}
        rebuilt, cursor = [], 0
        for idx, m in enumerate(blocks):
            rebuilt.append(body[cursor:m.start()])
            rebuilt.append(replacement_map[idx])
            cursor = m.end()
        rebuilt.append(body[cursor:])
        return template[:a] + "".join(rebuilt) + template[b:]

    def _reorder_projects(self, template: str, matched_keywords: set[str], jd_text: str) -> tuple[str, list[str]]:
        a = template.index(r"\section{Projects/Experience}") + len(r"\section{Projects/Experience}")
        b = template.index(r"\section{Education}", a)
        body = template[a:b]
        parts = re.split(r"(?=^[ \t]*\\begin\{twocolentry\}\{)", body, flags=re.MULTILINE)
        if len(parts) < 3:
            return template, []
        prefix, projects = parts[0], parts[1:]
        ranked = []
        for idx, block in enumerate(projects):
            title = _project_title(block)
            score = sum(1 for kw in matched_keywords if _phrase_or_term_matches(kw, block))
            if title and _phrase_or_term_matches(title, jd_text):
                score += 2
            ranked.append((score, -idx, block, title))
        ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return template[:a] + prefix + "".join(x[2] for x in ranked) + template[b:], [x[3] for x in ranked if x[3]]

    def tailor(self, jd_text: str, title: str = "") -> TailoredResume:
        if not str(jd_text or "").strip():
            raise ValueError("Job description is empty. Refresh/store the job description before tailoring a resume.")

        master = self.master_template_path.read_text(encoding="utf-8")
        self._validate_template(master)
        inventory = extract_keyword_inventory(jd_text, title)
        report_rows = self._match_check(inventory["all_literals"], master)

        safe_additions: list[dict] = []
        unsupported: list[dict] = []
        gap_classifications: list[dict] = []
        for row in report_rows:
            kw = row["keyword"]
            if row["match_type"] == "exact":
                continue
            supported, evidence = _supported_evidence(kw, master, self.profile)
            applicable = _applicable_keyword(kw, self.profile)
            if supported and applicable:
                safe_additions.append({
                    "keyword": kw,
                    "evidence": evidence,
                    "match_type": row["match_type"],
                    "placement": "skills_or_supported_project_bullet",
                })
            else:
                classification = "checker_glitch" if not kw.strip() or norm(kw) in MALFORMED_TITLE_FRAGMENTS else _classify_gap(kw)
                reason = (
                    "Supported, but not specific enough for safe insertion"
                    if supported else
                    "No evidence in master resume or verified profile/project data"
                )
                unsupported.append({"keyword": kw, "reason": reason, "classification": classification})
                gap_classifications.append({
                    "keyword": kw,
                    "classification": classification,
                    "evidence": evidence,
                    "action": (
                        "do_not_auto_add; confirm genuine experience before adding"
                        if classification == "authenticity_risk" else
                        "leave as gap" if classification == "real_content_gap" else
                        "exclude from ATS gap score"
                    ),
                })

        tailored = master
        added: list[str] = []
        rewritten_bullets: list[dict] = []

        # Tailor the professional summary from source-verified summary options,
        # adding only supported JD wording and a source-verified project metric.
        tailored, summary_tailoring = _tailor_professional_summary(
            tailored, self.content_bank, report_rows, master, self.profile, jd_text
        )
        added.extend(summary_tailoring.get("inserted_keywords", []))

        # Skill section is allowed to carry supported ATS terms; this does not
        # claim project experience beyond the evidence already present.
        skill_priority = {"vector dbs": 0, "llm integration": 1, "transformer-based models": 2}
        for item in sorted(safe_additions, key=lambda x: skill_priority.get(norm(x["keyword"]), 50)):
            keyword = item["keyword"]
            if norm(keyword) in ROLE_TITLE_ONLY_TERMS:
                continue
            if not (_skill_like(keyword) or norm(keyword) in {
                "vector dbs", "vector db", "llm integration", "transformer-based models",
            }):
                continue
            tailored, changed = _insert_skill_keyword(tailored, keyword)
            if changed:
                added.append(keyword)

        # Project-level tailoring: exact JD terminology is inserted only when
        # the project block/profile proves the underlying capability.
        original_blocks = _project_blocks(tailored)
        rewritten_blocks: list[str] = []
        stronger_bullet_selections: list[dict] = []
        metric_lock_report: dict = {}
        for block in original_blocks:
            title_name = _project_title(block)
            project = next((p for p in self.profile.get("projects", []) or [] if norm(p.get("title", "")) == norm(title_name)), None)
            bank_project = _content_bank_project(self.content_bank, title_name)
            updated = block
            if bank_project:
                updated, changes = _apply_stronger_project_bullets(updated, bank_project, jd_text)
                stronger_bullet_selections.extend(changes)
                if bank_project.get("metric_locks"):
                    metric_lock_report[title_name] = list(bank_project.get("metric_locks"))
            for item in safe_additions:
                kw = item["keyword"]
                if norm(kw) in ROLE_TITLE_ONLY_TERMS:
                    continue
                if not _project_keyword_support(kw, updated, project):
                    continue
                # Prefer a concrete project rewrite over a tacked-on suffix.
                rewritten, changed_rewrite, detail_rewrite = _rewrite_supported_project_bullet(updated, kw, project)
                if changed_rewrite and detail_rewrite:
                    updated = rewritten
                    added.append(kw)
                    rewritten_bullets.append({"project": title_name, **detail_rewrite})
                    continue

                # Avoid a second mechanical alias expansion after a concrete rewrite already covered it.
                if norm(kw) in {"llm-based", "llm based"} and _phrase_or_term_matches("llm integration", updated):
                    continue

                # Prefer expanding a JD phrase over adding another duplicate word.
                bullets = _bullet_matches(updated)
                expanded = False
                for idx, (raw, _plain, _count) in enumerate(bullets):
                    candidate, ok = _phrase_expand_in_bullet(raw, kw)
                    if ok:
                        updated = _replace_bullet(updated, idx, candidate)
                        added.append(kw)
                        rewritten_bullets.append({
                            "project": title_name,
                            "bullet_index": idx + 1,
                            "keyword": kw,
                            "change": "expanded supported shorthand to JD wording",
                        })
                        expanded = True
                        break
                if expanded:
                    continue
                updated, changed, detail = _insert_supported_keyword_into_bullet(updated, kw, project)
                if changed and detail:
                    added.append(kw)
                    rewritten_bullets.append({"project": title_name, **detail})
            rewritten_blocks.append(updated)

        # Put rewritten project blocks back in place before relevance reordering.
        a = tailored.index(r"\section{Projects/Experience}") + len(r"\section{Projects/Experience}")
        b = tailored.index(r"\section{Education}", a)
        body = tailored[a:b]
        parts = re.split(r"(?=^[ \t]*\\begin\{twocolentry\}\{)", body, flags=re.MULTILINE)
        if len(parts) >= 3 and len(rewritten_blocks) == len(parts[1:]):
            tailored = tailored[:a] + parts[0] + "".join(rewritten_blocks) + tailored[b:]

        tailored, format_repairs = _compact_overlong_bullets(tailored)
        rewritten_bullets.extend(format_repairs)

        matched_set = {norm(x["keyword"]) for x in report_rows if x["in_resume"] or any(norm(s["keyword"]) == norm(x["keyword"]) for s in safe_additions)}
        tailored = self._reorder_skills(tailored, matched_set)
        tailored, project_order = self._reorder_projects(tailored, matched_set, jd_text)

        tailored, verb_fixes, repeated_verbs = _rewrite_repeated_verbs(tailored)

        bullet_counts = _all_bullet_word_counts(tailored)
        if any(c > 25 for c in bullet_counts):
            raise ValueError(f"tailored bullet exceeds 25 words: {max(bullet_counts)} words")

        quant_gaps: list[dict] = []
        analysis_data_flags: list[dict] = []
        for block in _project_blocks(tailored):
            title_name = _project_title(block)
            for idx, (raw, _plain, _count) in enumerate(_bullet_matches(block)):
                if not _bullet_has_number(raw):
                    quant_gaps.append({"project": title_name, "bullet_index": idx + 1, "reason": "No hard number/percentage/timeframe found; not invented"})
                plain = _bullet_plain(raw).lower()
                if re.search(r"\banalysis\s+(?:and\s+)?data\b|\bdata\s+(?:and\s+)?analysis\b", plain):
                    analysis_data_flags.append({"project": title_name, "bullet_index": idx + 1, "text": _bullet_plain(raw)})

        content_bank_options = _rank_content_bank_options(self.content_bank, jd_text, title)
        checker_glitch_keywords = {norm(x["keyword"]) for x in gap_classifications if x["classification"] == "checker_glitch"}
        effective_rows = [x for x in report_rows if norm(x["keyword"]) not in checker_glitch_keywords]
        cv_check = _resume_cv_check_rows(effective_rows)
        cv_check["raw_total_keywords_checked"] = len(report_rows)
        cv_check["excluded_checker_glitches"] = len(report_rows) - len(effective_rows)
        bullet_style_check = _bullet_style_check(tailored)

        master_metrics = _extract_metrics(master)
        missing_metrics = [m for m in master_metrics if m not in _extract_metrics(tailored)]
        metrics_preserved = not missing_metrics
        if not metrics_preserved:
            raise ValueError(f"resume integrity failure: metrics lost during tailoring: {missing_metrics}")
        for project_title, locks in metric_lock_report.items():
            master_project = next((b for b in _project_blocks(master) if norm(_project_title(b)) == norm(project_title)), "")
            tailored_project = next((b for b in _project_blocks(tailored) if norm(_project_title(b)) == norm(project_title)), "")
            if master_project and tailored_project:
                master_plain = _bullet_plain(master_project).replace(r"\%", "%").lower()
                plain = _bullet_plain(tailored_project).replace(r"\%", "%").lower()
                required_locks = [m for m in locks if str(m).lower() in master_plain]
                missing_locks = [m for m in required_locks if str(m).lower() not in plain]
                if missing_locks:
                    raise ValueError(f"resume integrity failure: metric locks lost for {project_title}: {missing_locks}")

        authenticity_flags = self._authenticity_scan(master, jd_text)
        authenticity_flags.extend(
            {
                "keyword": item["keyword"],
                "classification": item["classification"],
                "action": item["action"],
            }
            for item in gap_classifications
            if item["classification"] == "authenticity_risk"
        )

        report = TailoringReport(
            authenticity_flags=authenticity_flags,
            keyword_inventory_count=len(inventory["single_word_keywords"]),
            phrase_inventory_count=len(inventory["phrase_keywords"]),
            second_pass_verified=bool(inventory.get("second_pass_verified")),
            matched_keywords=report_rows,
            safe_additions=safe_additions,
            unsupported_keywords=unsupported,
            added_keywords=list(dict.fromkeys(added)),
            rewritten_bullets=rewritten_bullets,
            reordered_projects=project_order,
            repeated_verb_fixes=verb_fixes,
            repeated_verbs_flagged=repeated_verbs,
            quantification_gaps=quant_gaps,
            analysis_data_repetition_flags=analysis_data_flags,
            bullet_word_counts=bullet_counts,
            metrics_preserved=metrics_preserved,
            preserved_metrics=master_metrics,
            missing_metrics=missing_metrics,
            verification={"page_count": None, "hyperlinks_checked": False, "linkedin_url": False, "github_url": False},
            content_bank_options=content_bank_options,
            cv_check=cv_check,
            stronger_bullet_selections=stronger_bullet_selections,
            metric_locks=metric_lock_report,
            bullet_style_check=bullet_style_check,
            summary_tailoring=summary_tailoring,
            gap_classifications=gap_classifications,
            prompt_spec="RESUME_ATS_AUTHENTICITY_PROMPT.md",
        )
        self._assert_structure(master, tailored)

        matched_skill_terms = [
            x["keyword"] for x in report_rows
            if x["in_resume"] and _applicable_keyword(x["keyword"], self.profile)
        ]
        return TailoredResume(
            tailored,
            list(dict.fromkeys(matched_skill_terms)),
            inventory["all_literals"],
            report.to_dict(),
        )

    def _assert_structure(self, original: str, tailored: str) -> None:
        markers = (
            r"\section{Professional Summary}", r"\section{Core Competencies / Skills}",
            r"\section{Projects/Experience}", r"\section{Education}",
            r"\section{Certifications}", r"\end{document}"
        )
        for marker in markers:
            if marker not in tailored:
                raise ValueError(f"resume structure missing after tailoring: {marker}")
        edu_marker = r"\section{Education}"
        if original[original.index(edu_marker):] != tailored[tailored.index(edu_marker):]:
            raise ValueError("resume integrity failure: Education/Certifications content changed")
        original_titles = sorted(_project_title(x) for x in _project_blocks(original))
        tailored_titles = sorted(_project_title(x) for x in _project_blocks(tailored))
        if original_titles != tailored_titles:
            raise ValueError("resume integrity failure: project set changed")


def verify_pdf(pdf_path: str | Path) -> dict:
    pdf = Path(pdf_path)
    if not pdf.is_file():
        raise RuntimeError(f"resume PDF not found: {pdf}")

    # PyMuPDF provides deep hyperlink/page-count verification, but it must not
    # become a hard prerequisite for native Indeed upload.  A generated file
    # with a valid PDF signature remains uploadable when fitz is unavailable;
    # the result explicitly records that deep verification was skipped.
    try:
        import fitz
    except Exception:
        with pdf.open("rb") as handle:
            signature = handle.read(5)
        if signature != b"%PDF-":
            raise RuntimeError("generated resume is not a valid PDF file")
        return {
            "verification_skipped": True,
            "verification_reason": "PyMuPDF unavailable",
            "one_page": None,
            "hyperlinks_checked": False,
            "hyperlink_count": None,
            "linkedin_url": None,
            "github_url": None,
        }

    doc = fitz.open(pdf)
    links = []
    for page in doc:
        links.extend(page.get_links())
    uris = [str(x.get("uri")) for x in links if x.get("uri")]
    linkedin_ok = any("linkedin.com/" in u.lower() for u in uris)
    github_ok = any("github.com/" in u.lower() for u in uris)
    result = {
        "page_count": doc.page_count,
        "one_page": doc.page_count == 1,
        "hyperlinks_checked": True,
        "hyperlink_count": len(uris),
        "linkedin_url": linkedin_ok,
        "github_url": github_ok,
    }
    doc.close()
    if not result["one_page"]:
        raise RuntimeError(f"tailored resume rendered to {result['page_count']} pages; one-page constraint failed")
    if not linkedin_ok or not github_ok:
        raise RuntimeError("tailored resume hyperlink verification failed for LinkedIn and/or GitHub")
    return result


def compile_latex(latex: str, output_dir: str | Path, filename: str = "resume") -> Path:
    executable = shutil.which("pdflatex")
    if not executable:
        raise RuntimeError("pdflatex is not installed")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    tex = output / f"{filename}.tex"
    tex.write_text(latex, encoding="utf-8")
    proc = subprocess.run(
        [executable, "-interaction=nonstopmode", "-halt-on-error", "-output-directory", str(output), str(tex)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=output,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stdout + "\n" + proc.stderr)[-6000:])
    pdf = output / f"{filename}.pdf"
    if not pdf.exists():
        raise RuntimeError("pdflatex reported success but no PDF was produced")
    return pdf
