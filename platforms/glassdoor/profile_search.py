import json
import re
from pathlib import Path

class ProfileSearch:
    """Search the supplied candidate data for evidence relevant to a form question.

    This is deliberately retrieval-first: the application question is matched
    against facts/projects/skills/certifications/preferences before an LLM is
    allowed to compose an answer. It never creates new candidate facts.
    """
    def __init__(self, profile_path=None):
        path = Path(profile_path) if profile_path else Path(__file__).with_name("profile.json")
        self.profile = json.loads(path.read_text(encoding="utf-8"))
        self.records = []
        self._build_records(self.profile)

    def _build_records(self, obj, path="profile"):
        if isinstance(obj, dict):
            for key, value in obj.items():
                self._build_records(value, f"{path}.{key}")
        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                self._build_records(value, f"{path}[{i}]")
        else:
            if obj is None or str(obj).strip() == "":
                return
            self.records.append({
                "field": path,
                "value": str(obj),
                "search": self._normal(path.replace("_", " ") + " " + str(obj))
            })

    @staticmethod
    def _normal(text):
        return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()

    @staticmethod
    def _tokens(text):
        return {x for x in ProfileSearch._normal(text).split() if len(x) >= 2}

    @staticmethod
    def _expand_tokens(tokens):
        aliases = {
            "rag": {"retrieval", "augmented", "generation", "retrieval-augmented", "vector", "embeddings"},
            "retrieval": {"rag", "vector", "embeddings"},
            "augmented": {"rag"},
            "generation": {"rag", "genai", "generative"},
            "genai": {"generative", "ai", "llm"},
            "generative": {"genai", "llm"},
            "llm": {"llms", "language", "model", "genai"},
            "llms": {"llm", "genai"},
            "ai": {"artificial", "intelligence", "genai", "llm"},
            "cloud": {"aws", "ec2", "s3", "iam", "rds"},
            "aws": {"cloud", "ec2", "s3", "iam", "rds"},
            "machine": {"learning", "pytorch", "tensorflow", "scikit"},
            "learning": {"machine", "pytorch", "tensorflow", "scikit"},
            "ml": {"machine", "learning", "pytorch", "tensorflow", "scikit"},
            "database": {"sql", "mysql", "faiss", "chromadb", "vector"},
            "databases": {"sql", "mysql", "faiss", "chromadb", "vector"},
            "api": {"apis", "rest", "fastapi", "flask", "gemini"},
            "apis": {"api", "rest", "fastapi", "flask", "gemini"},
            "automation": {"n8n", "workflow", "webhook"},
            "projects": {"project"},
        }
        out = set(tokens)
        for token in list(tokens):
            out.update(aliases.get(token, set()))
        return out

    def search(self, question, limit=12):
        q = self._normal(question)
        qt = self._expand_tokens(self._tokens(question))
        if not qt:
            return []

        # Common form-language terms carry little retrieval value.
        stop = {"what", "which", "how", "many", "much", "your", "you", "have",
                "are", "do", "did", "does", "with", "for", "the", "and", "or",
                "can", "please", "tell", "us", "about", "years", "year", "experience"}
        important = qt - stop
        scored = []
        for rec in self.records:
            rt = self._tokens(rec["search"])
            overlap = len(important & rt) if important else len(qt & rt)
            phrase_bonus = 0
            # Exact field/value phrases are strong evidence.
            if q and q in rec["search"]:
                phrase_bonus += 8
            score = overlap * 3 + phrase_bonus
            if score <= 0:
                continue
            scored.append((score, rec))
        scored.sort(key=lambda x: (-x[0], len(x[1]["field"])))
        return [rec for score, rec in scored[:limit]]

    def evidence_text(self, question, limit=12):
        rows = self.search(question, limit=limit)
        if not rows:
            return "NO MATCHING PROFILE EVIDENCE FOUND"
        return "\n".join(f"- {r['field']} = {r['value']}" for r in rows)
