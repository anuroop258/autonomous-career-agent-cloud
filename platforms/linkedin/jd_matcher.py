import json
import re
from pathlib import Path


class JDMatcher:
    """Deterministic, fresher-friendly JD matcher.

    Design goals:
      * Keep explicit positive minimum experience and seniority as hard blockers.
      * Do not require an AI keyword for every software-development role.
      * Recognize internships, graduate/trainee/new-grad and junior software titles.
      * Score AI roles and software roles through separate evidence tracks.
      * Keep the output explainable so the browser agent can decide why a job was kept.
    """

    DEFAULT_SOFTWARE_ROLE_TERMS = (
        "software engineer", "software developer", "sde", "sde 1", "sde-1",
        "junior software engineer", "junior software developer",
        "associate software engineer", "associate developer",
        "backend engineer", "backend developer", "back end engineer", "back end developer",
        "full stack engineer", "full stack developer", "frontend engineer", "frontend developer",
        "front end engineer", "front end developer",
        "python developer", "python engineer",
        "java developer", "java engineer",
        "application developer", "application engineer",
        "web developer", "web engineer",
        "developer", "programmer", "software development engineer",
    )
    DEFAULT_ENTRY_TITLE_TERMS = (
        "intern", "internship", "trainee", "graduate trainee", "graduate engineer trainee",
        "new grad", "new graduate", "recent graduate", "fresher", "freshers",
        "entry level", "entry-level", "junior", "associate", "apprentice",
        "campus", "early career", "early-career", "student",
    )
    DEFAULT_SENIOR_TERMS = (
        "senior", "sr", "lead", "staff", "principal", "manager", "director",
        "head", "architect", "vp", "vice president", "chief", "expert",
        "intermediate", "mid-level", "mid level",
    )
    DEFAULT_SOFTWARE_SKILLS = (
        "python", "java", "c++", "c", "javascript", "typescript", "sql",
        "mysql", "postgresql", "postgres", "rest apis", "rest api",
        "fastapi", "flask", "spring", "node.js", "nodejs", "react",
        "html", "css", "git", "github", "docker", "aws", "azure", "gcp",
        "pandas", "numpy", "data structures", "algorithms", "oop",
        "object oriented programming", "api", "apis",
    )

    def __init__(self, base_dir="."):
        base = Path(base_dir)
        self.profile = json.loads((base / "profile.json").read_text(encoding="utf-8"))
        self.config = json.loads((base / "role_config.json").read_text(encoding="utf-8"))

        self.profile_skills = [self._norm(x) for x in self.profile.get("skills", [])]
        self.skill_display = {self._norm(x): x for x in self.profile.get("skills", [])}

        self.roles = [self._norm(x) for x in self.config.get("primary", [])]

        self.aliases = {
            "llms": ["llm", "large language model", "large language models"],
            "generative ai": ["genai", "generative artificial intelligence", "generative-ai"],
            "rag": ["retrieval augmented generation", "retrieval-augmented generation"],
            "google gemini api": ["gemini", "gemini api"],
            "fastapi": ["fast api"],
            "machine learning": ["ml"],
            "deep learning": ["dl"],
            "pytorch": ["torch"],
            "chromadb": ["chroma db", "chroma"],
            "chroma db": ["chromadb", "chroma"],
            "webhook based orchestration": ["webhook orchestration", "webhooks"],
            "langgraph": ["lang graph"],
            "langchain": ["lang chain"],
            "rest apis": ["rest api", "restful api", "restful apis"],
            "postgresql": ["postgres"],
            "javascript": ["js"],
            "typescript": ["ts"],
            "c++": ["cpp"],
        }

    def match(self, title, jd_text):
        title = title or ""
        jd_text = jd_text or ""
        combined = self._norm(title + "\n" + jd_text)
        title_norm = self._norm(title)

        target_terms = [self._norm(x) for x in self.config.get("skill_terms", [])]
        target_hits = [
            self._display_config_term(x)
            for x in target_terms
            if self._contains_term_with_alias(combined, x)
        ]

        ai_terms = [self._norm(x) for x in self.config.get("ai_signal_terms", [])]
        ai_hits = [
            self._display_config_term(x)
            for x in ai_terms
            if self._contains_term(combined, x)
        ]
        ai_relevant = len(ai_hits) >= int(self.config.get("min_ai_signal_hits", 1))

        role_hits = [r for r in self.roles if self._role_matches(title_norm, r)]

        software_terms = tuple(
            self._norm(x)
            for x in self.config.get("software_role_terms", self.DEFAULT_SOFTWARE_ROLE_TERMS)
        )
        software_role_hits = [
            x for x in software_terms if self._contains_term(title_norm, x)
        ]

        entry_terms = tuple(
            self._norm(x)
            for x in self.config.get("entry_level_title_terms", self.DEFAULT_ENTRY_TITLE_TERMS)
        )
        entry_title_hits = [
            x for x in entry_terms if self._contains_term(title_norm, x)
        ]

        seniority_hit = self._first_title_term(title_norm, self.config.get("senior_title_terms", self.DEFAULT_SENIOR_TERMS))
        hard_seniority_block = seniority_hit is not None

        software_skill_terms = tuple(
            self._norm(x)
            for x in self.config.get("software_skill_terms", self.DEFAULT_SOFTWARE_SKILLS)
        )
        software_skill_hits = [
            self._display_profile_or_term(x)
            for x in software_skill_terms
            if self._contains_term_with_alias(combined, x)
        ]

        # Also surface direct profile skills for diagnostics.
        matched = []
        missing = []
        for skill_norm in self.profile_skills:
            if self._contains_skill(combined, skill_norm):
                matched.append(self.skill_display[skill_norm])
            else:
                missing.append(self.skill_display[skill_norm])

        score, components = self._score(
            role_hits=role_hits,
            software_role_hits=software_role_hits,
            entry_title_hits=entry_title_hits,
            target_hits=target_hits,
            ai_hits=ai_hits,
            software_skill_hits=software_skill_hits,
            title_norm=title_norm,
            combined=combined,
        )

        experience_score, experience_note, experience_ok = self._experience_fit(
            title_norm, combined
        )
        if not experience_ok:
            experience_mode = "hard_block"
        elif "Accepted entry-level" in experience_note:
            experience_mode = "zero_minimum"
        elif "Fresher/entry-level" in experience_note or "No explicit" not in experience_note:
            experience_mode = "entry_signal"
        elif "Stretch entry-level" in experience_note:
            experience_mode = "stretch_range"
        else:
            experience_mode = "unspecified"

        score = min(100, score + experience_score)

        threshold = int(self.config.get("jd_match_threshold", 55))
        software_threshold = int(self.config.get("software_match_threshold", max(40, threshold - 10)))
        intern_threshold = int(self.config.get("intern_match_threshold", max(35, threshold - 15)))

        is_ai_track = bool(role_hits or target_hits or ai_relevant)
        is_software_track = bool(software_role_hits)
        is_entry_track = bool(entry_title_hits)

        # Selection policy:
        # 1) senior title / explicit mandatory positive minimum -> hard reject.
        # 2) AI track qualifies using normal threshold.
        # 3) software titles can qualify without AI keywords if technical overlap is meaningful.
        # 4) intern/entry titles get a lower threshold, but still require real technical evidence.
        # 5) no generic "any developer" qualification without sufficient evidence.
        reasons = []
        hard_block = hard_seniority_block or not experience_ok

        if hard_seniority_block:
            reasons.append(f"seniority/title block: {seniority_hit}")
        if not experience_ok:
            reasons.append(experience_note)

        min_software_skills = int(self.config.get("min_software_skill_hits", 2))
        min_intern_skills = int(self.config.get("min_intern_skill_hits", 1))

        qualifies_ai = (
            not hard_block
            and is_ai_track
            and score >= threshold
            and (ai_relevant or bool(role_hits) or len(target_hits) >= 2)
        )
        qualifies_software = (
            not hard_block
            and is_software_track
            and len(software_skill_hits) >= min_software_skills
            and score >= software_threshold
        )
        qualifies_intern = (
            not hard_block
            and is_entry_track
            and len(software_skill_hits) >= min_intern_skills
            and score >= intern_threshold
            and (is_software_track or ai_relevant or len(target_hits) >= 1)
        )

        eligible = bool(qualifies_ai or qualifies_software or qualifies_intern)

        if not eligible:
            if not (is_ai_track or is_software_track or is_entry_track):
                reasons.append("title/content lacks a recognized target, software, or entry-level track")
            elif is_software_track and len(software_skill_hits) < min_software_skills:
                reasons.append(f"only {len(software_skill_hits)} relevant software skill(s); need {min_software_skills}")
            if score < min(threshold, software_threshold if is_software_track else threshold):
                reasons.append(f"score {score} below applicable threshold")
            if is_ai_track and not ai_relevant and not is_software_track:
                reasons.append("insufficient AI relevance for AI-only track")

        track = "ai" if qualifies_ai else "software" if qualifies_software else "intern" if qualifies_intern else "none"
        return {
            "score": score,
            "threshold": threshold,
            "applicable_threshold": threshold if track == "ai" else software_threshold if track == "software" else intern_threshold,
            "eligible": eligible,
            "match_track": track,
            "matched_skills": matched,
            "missing_skills": missing,
            "role_hits": [self._display_role(x) for x in role_hits],
            "software_role_hits": software_role_hits,
            "entry_title_hits": entry_title_hits,
            "target_skill_hits": target_hits,
            "software_skill_hits": software_skill_hits,
            "ai_signal_hits": ai_hits,
            "ai_relevant": ai_relevant,
            "role_relevant": bool(role_hits),
            "experience_ok": experience_ok,
            "experience_mode": experience_mode,
            "experience_note": experience_note,
            "seniority_block": seniority_hit,
            "rejection_reasons": reasons,
            "score_components": {**components, "experience": experience_score},
        }

    def _score(self, *, role_hits, software_role_hits, entry_title_hits,
               target_hits, ai_hits, software_skill_hits, title_norm, combined):
        # Keep the total understandable and capped at 85 before experience bonus.
        preferred_role = 32 if role_hits else 0
        software_role = 22 if software_role_hits else 0
        entry_bonus = 6 if entry_title_hits else 0
        ai_bonus = min(12, len(ai_hits) * 3)
        target_bonus = min(25, len(target_hits) * 5)
        software_skill_bonus = min(25, len(software_skill_hits) * 5)

        # Small direct profile overlap bonus helps junior roles without making generic
        # cloud/soft-skill matches dominate.
        return (
            preferred_role
            + software_role
            + entry_bonus
            + ai_bonus
            + target_bonus
            + software_skill_bonus
        ), {
            "preferred_role": preferred_role,
            "software_role": software_role,
            "entry_title": entry_bonus,
            "ai_signal": ai_bonus,
            "target_skill": target_bonus,
            "software_skill": software_skill_bonus,
        }

    def _experience_fit(self, title, text):
        cfg_max = int(self.config.get("max_experience_years", 3))
        entry_only = bool(self.config.get("entry_level_only", True))

        senior_hit = self._first_title_term(title, self.config.get("senior_title_terms", self.DEFAULT_SENIOR_TERMS))
        if senior_hit:
            return 0, f"Senior/non-entry-level title signal detected: {senior_hit}.", False

        text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")

        accepted_ranges = {
            str(x).strip().lower().replace(" ", "")
            for x in self.config.get("accepted_entry_level_ranges", ["0-1", "0-2", "0-3"])
        }

        accepted = []
        accepted_spans = []
        for m in re.finditer(r"\b0\s*(?:to|-)\s*(\d+)\s*(?:years?|yrs?)\b", text, re.I):
            high = int(m.group(1))
            value = f"0-{high}"
            if value in accepted_ranges and high <= cfg_max:
                accepted.append(value)
                accepted_spans.append((m.start(), m.end()))

        requirements = self._experience_requirements(text, ignored_spans=accepted_spans)

        # Explicit minimum wording is a hard gate.
        explicit_minimum = []
        for r in requirements:
            if r["is_range"]:
                # A range such as 1-3 is a softer mismatch for a fresher unless explicitly
                # described as required/minimum.
                if self._is_explicit_minimum_language(r["display"], text, r["search_start"]):
                    if r["lower"] > 0:
                        explicit_minimum.append(r)
                    elif r["upper"] > cfg_max:
                        explicit_minimum.append(r)
            else:
                if r["lower"] > 0:
                    explicit_minimum.append(r)

        if explicit_minimum:
            r = explicit_minimum[0]
            return (
                0,
                f"JD explicitly requires at least {r['display']}; candidate has 0 professional years.",
                False,
            )

        # High ranges/seniority language that are not explicitly minimum are still blocked.
        for r in requirements:
            if r["lower"] > cfg_max and r["is_range"]:
                return 0, f"Experience range {r['display']} exceeds entry-level maximum.", False

        if accepted:
            return 15, f"Accepted entry-level experience range detected ({accepted[0]}).", True

        if re.search(
            r"\b(?:fresher|freshers|entry[- ]level|graduate trainee|graduate engineer trainee|new graduate|recent graduate|new grad|no (?:prior\s+)?experience required|without experience|0 years?)\b",
            text,
            re.I,
        ):
            return 15, "Fresher/entry-level/no-experience language detected.", True

        # A positive-minimum range such as 1-3 is still incompatible with a 0-year
        # candidate. The matcher is deliberately loosened around role/skill relevance,
        # not by ignoring a stated experience requirement.
        positive_ranges = [r for r in requirements if r["is_range"] and r["lower"] > 0]
        if positive_ranges:
            r = positive_ranges[0]
            return 0, f"JD states {r['display']}; candidate has 0 professional years.", False

        return 10, "No explicit positive minimum experience requirement detected.", True

    def _experience_requirements(self, text, ignored_spans=None):
        ignored_spans = ignored_spans or []
        found = []

        def ignored(m):
            return any(m.start() < e and m.end() > s for s, e in ignored_spans)

        range_spans = []
        for m in re.finditer(r"\b(\d+)\s*(?:to|-)\s*(\d+)\s*(?:years?|yrs?)\b", text, re.I):
            if ignored(m):
                continue
            low, high = int(m.group(1)), int(m.group(2))
            if high < low:
                low, high = high, low
            range_spans.append((m.start(), m.end()))
            found.append({
                "lower": low, "upper": high,
                "display": re.sub(r"\s+", " ", m.group(0)).strip(),
                "is_range": True, "search_start": m.start(),
            })

        patterns = [
            r"\b(?:minimum|at least|required|requires?|must have|must possess|need(?:s)?|should have)\b[^.\n]{0,80}?\b(\d+)\s*\+?\s*(?:years?|yrs?)\b",
            r"\b(\d+)\s*\+\s*(?:years?|yrs?)\b[^.\n]{0,80}?\bexperience\b",
            r"\b(\d+)\s*(?:years?|yrs?)\b\s+(?:of\s+)?(?:relevant\s+|professional\s+|hands[- ]on\s+|industry\s+)?experience\b",
            r"\bexperience\b[^.\n]{0,50}?\b(\d+)\s*(?:years?|yrs?)\b",
        ]
        for pat in patterns:
            for m in re.finditer(pat, text, re.I):
                if ignored(m) or any(m.start() < e and m.end() > s for s, e in range_spans):
                    continue
                found.append({
                    "lower": int(m.group(1)), "upper": int(m.group(1)),
                    "display": re.sub(r"\s+", " ", m.group(0)).strip(),
                    "is_range": False, "search_start": m.start(),
                })

        unique = {}
        for item in found:
            key = (item["lower"], item["upper"], item["is_range"])
            unique.setdefault(key, item)
        return list(unique.values())

    def _is_explicit_minimum_language(self, display, full_text, start):
        window = full_text[max(0, start - 80): start + 120]
        return re.search(
            r"\b(?:minimum|at least|required|requires?|must have|must possess|need(?:s)?|should have)\b",
            window,
            re.I,
        ) is not None

    def _contains_skill(self, text, skill):
        return self._contains_term_with_alias(text, skill)

    def _contains_term_with_alias(self, text, term):
        if self._contains_term(text, term):
            return True
        for alias in self.aliases.get(term, []):
            if self._contains_term(text, self._norm(alias)):
                return True
        return False

    def _contains_term(self, text, term):
        if not term:
            return False
        if len(term) <= 4:
            return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None
        return term in text

    def _role_matches(self, title, role):
        if role in title:
            return True
        if role == "generative ai engineer":
            return "genai engineer" in title or "generative ai" in title
        if role == "ai/ml engineer":
            return "ai ml engineer" in title or "ai engineer" in title
        if role == "machine learning engineer":
            return "ml engineer" in title or "machine learning engineer" in title
        if role == "python ai engineer":
            return "python engineer" in title and ("ai" in title or "ml" in title)
        return False

    def _first_title_term(self, title, terms):
        for raw in terms:
            term = self._norm(raw)
            if term and self._contains_term(title, term):
                return raw
        return None

    def _display_profile_or_term(self, norm):
        return self.skill_display.get(norm, norm)

    def _display_config_term(self, norm):
        for raw in self.config.get("skill_terms", []) + self.config.get("ai_signal_terms", []):
            if self._norm(raw) == norm:
                return raw
        return norm

    def _display_role(self, role):
        for x in self.config.get("primary", []):
            if self._norm(x) == role:
                return x
        return role

    def _norm(self, text):
        text = str(text).lower().replace("&", " and ")
        text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+.#? -]+", " ", text)).strip()
