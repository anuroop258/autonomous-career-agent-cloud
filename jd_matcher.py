import json
import re
from pathlib import Path
from src.application.common.jd_keyword_inventory import (
    build_candidate_evidence,
    exact_match_keywords,
    extract_full_jd_keywords,
)


class JDMatcher:
    """
    Deterministic, fresher-friendly JD matcher.

    IMPORTANT:
    This preserves the existing Naukri agent contract.

    Output keys expected by naukri_agent.py:
        score
        threshold
        applicable_threshold
        eligible
        match_track
        matched_skills
        missing_skills
        role_hits
        software_role_hits
        entry_title_hits
        target_skill_hits
        software_skill_hits
        ai_signal_hits
        ai_relevant
        role_relevant
        experience_ok
        experience_mode
        experience_note
        seniority_block
        rejection_reasons
        score_components
    """

    DEFAULT_SOFTWARE_ROLE_TERMS = (
        "software engineer",
        "software developer",
        "sde",
        "sde 1",
        "sde-1",
        "junior software engineer",
        "junior software developer",
        "associate software engineer",
        "associate developer",
        "backend engineer",
        "backend developer",
        "back end engineer",
        "back end developer",
        "full stack engineer",
        "full stack developer",
        "frontend engineer",
        "frontend developer",
        "front end engineer",
        "front end developer",
        "python developer",
        "python engineer",
        "java developer",
        "java engineer",
        "application developer",
        "application engineer",
        "web developer",
        "web engineer",
        "developer",
        "programmer",
        "software development engineer",
    )

    DEFAULT_ENTRY_TITLE_TERMS = (
        "intern",
        "internship",
        "trainee",
        "graduate trainee",
        "graduate engineer trainee",
        "new grad",
        "new graduate",
        "recent graduate",
        "fresher",
        "freshers",
        "entry level",
        "entry-level",
        "junior",
        "associate",
        "apprentice",
        "campus",
        "early career",
        "early-career",
        "student",
    )

    DEFAULT_SENIOR_TERMS = (
        "senior",
        "sr",
        "lead",
        "staff",
        "principal",
        "manager",
        "director",
        "head",
        "architect",
        "vp",
        "vice president",
        "chief",
        "expert",
        "intermediate",
        "mid-level",
        "mid level",
    )

    DEFAULT_SOFTWARE_SKILLS = (
        "python",
        "java",
        "c++",
        "c",
        "javascript",
        "typescript",
        "sql",
        "mysql",
        "postgresql",
        "postgres",
        "rest apis",
        "rest api",
        "fastapi",
        "flask",
        "spring",
        "node.js",
        "nodejs",
        "react",
        "html",
        "css",
        "git",
        "github",
        "docker",
        "aws",
        "azure",
        "gcp",
        "pandas",
        "numpy",
        "data structures",
        "algorithms",
        "oop",
        "object oriented programming",
        "api",
        "apis",
    )

    def __init__(self, base_dir="."):
        base = Path(base_dir)

        self.profile = json.loads(
            (base / "profile.json").read_text(
                encoding="utf-8"
            )
        )

        self.config = json.loads(
            (base / "role_config.json").read_text(
                encoding="utf-8"
            )
        )

        master_resume_path = base / "resume" / "master_resume.tex"
        if not master_resume_path.exists():
            master_resume_path = base.parent / "resume" / "master_resume.tex"
        try:
            master_resume_text = master_resume_path.read_text(encoding="utf-8") if master_resume_path.exists() else ""
        except OSError:
            master_resume_text = ""
        self.jd_evidence_text = build_candidate_evidence(self.profile, master_resume_text)

        self.profile_skills = [
            self._norm(x)
            for x in self.profile.get(
                "skills",
                []
            )
        ]

        self.skill_display = {
            self._norm(x): x
            for x in self.profile.get(
                "skills",
                []
            )
        }

        self.roles = [
            self._norm(x)
            for x in self.config.get(
                "primary",
                []
            )
        ]

        self.aliases = {
            "llms": [
                "llm",
                "large language model",
                "large language models",
            ],

            "generative ai": [
                "genai",
                "generative artificial intelligence",
                "generative-ai",
            ],

            "rag": [
                "retrieval augmented generation",
                "retrieval-augmented generation",
            ],

            "google gemini api": [
                "gemini",
                "gemini api",
            ],

            "fastapi": [
                "fast api",
            ],

            "machine learning": [
                "ml",
            ],

            "deep learning": [
                "dl",
            ],

            "pytorch": [
                "torch",
            ],

            "chromadb": [
                "chroma db",
                "chroma",
            ],

            "chroma db": [
                "chromadb",
                "chroma",
            ],

            "webhook based orchestration": [
                "webhook orchestration",
                "webhooks",
            ],

            "langgraph": [
                "lang graph",
            ],

            "langchain": [
                "lang chain",
            ],

            "rest apis": [
                "rest api",
                "restful api",
                "restful apis",
            ],

            "postgresql": [
                "postgres",
            ],

            "javascript": [
                "js",
            ],

            "typescript": [
                "ts",
            ],

            "c++": [
                "cpp",
            ],
        }

    # ============================================================
    # MAIN MATCH
    # ============================================================

    def match(self, title, jd_text):

        title = title or ""
        jd_text = jd_text or ""

        combined = self._norm(
            title + "\n" + jd_text
        )

        title_norm = self._norm(title)

        # Full-JD literal matching goes beyond configured technical skills.
        # Soft skills and other content words contribute bounded evidence but
        # cannot bypass role/seniority/experience safety gates.
        jd_keyword_inventory = extract_full_jd_keywords(title, jd_text)
        jd_exact = exact_match_keywords(jd_keyword_inventory["all_keywords"], self.jd_evidence_text)
        jd_soft = exact_match_keywords(jd_keyword_inventory["soft_skill_keywords"], self.jd_evidence_text)
        jd_exact_hits = jd_exact["matched"]
        jd_exact_missing = jd_exact["missing"]
        jd_exact_score = min(18, len(jd_exact_hits) // 3 + min(8, len(jd_soft["matched"])))

        # --------------------------------------------------------
        # Naukri title experience range
        #
        # The title's "0 to X years" range is the job-board's explicit
        # experience metadata. Treat it as authoritative when it is a
        # supported zero-minimum entry-level range. This prevents unrelated
        # numbers elsewhere in a noisy JD from overriding the actual
        # Naukri experience range.
        # --------------------------------------------------------
        title_experience_override = self._title_zero_minimum_range(title_norm)

        # --------------------------------------------------------
        # Target/profile skills
        # --------------------------------------------------------

        target_terms = [
            self._norm(x)
            for x in self.config.get(
                "skill_terms",
                []
            )
        ]

        target_hits = [
            self._display_config_term(x)
            for x in target_terms
            if self._contains_term_with_alias(
                combined,
                x
            )
        ]

        # --------------------------------------------------------
        # AI signals
        # --------------------------------------------------------

        ai_terms = [
            self._norm(x)
            for x in self.config.get(
                "ai_signal_terms",
                []
            )
        ]

        ai_hits = [
            self._display_config_term(x)
            for x in ai_terms
            if self._contains_term(
                combined,
                x
            )
        ]

        ai_relevant = (
            len(ai_hits)
            >= int(
                self.config.get(
                    "min_ai_signal_hits",
                    1
                )
            )
        )

        # --------------------------------------------------------
        # Primary role matching
        # --------------------------------------------------------

        role_hits = [
            r
            for r in self.roles
            if self._role_matches(
                title_norm,
                r
            )
        ]

        # --------------------------------------------------------
        # Software role
        # --------------------------------------------------------

        software_terms = tuple(
            self._norm(x)
            for x in self.config.get(
                "software_role_terms",
                self.DEFAULT_SOFTWARE_ROLE_TERMS
            )
        )

        software_role_hits = [
            x
            for x in software_terms
            if self._contains_term(
                title_norm,
                x
            )
        ]

        # --------------------------------------------------------
        # Entry-level role
        # --------------------------------------------------------

        entry_terms = tuple(
            self._norm(x)
            for x in self.config.get(
                "entry_level_title_terms",
                self.DEFAULT_ENTRY_TITLE_TERMS
            )
        )

        entry_title_hits = [
            x
            for x in entry_terms
            if self._contains_term(
                title_norm,
                x
            )
        ]

        # --------------------------------------------------------
        # Seniority
        # --------------------------------------------------------

        seniority_hit = self._first_title_term(
            title_norm,
            self.config.get(
                "senior_title_terms",
                self.DEFAULT_SENIOR_TERMS
            )
        )

        hard_seniority_block = (
            seniority_hit is not None
        )

        # --------------------------------------------------------
        # Software skills
        # --------------------------------------------------------

        software_skill_terms = tuple(
            self._norm(x)
            for x in self.config.get(
                "software_skill_terms",
                self.DEFAULT_SOFTWARE_SKILLS
            )
        )

        software_skill_hits = [
            self._display_profile_or_term(x)
            for x in software_skill_terms
            if self._contains_term_with_alias(
                combined,
                x
            )
        ]

        # --------------------------------------------------------
        # Direct profile skill matches
        # --------------------------------------------------------

        matched = []
        missing = []

        for skill_norm in self.profile_skills:

            if self._contains_skill(
                combined,
                skill_norm
            ):
                matched.append(
                    self.skill_display[
                        skill_norm
                    ]
                )
            else:
                missing.append(
                    self.skill_display[
                        skill_norm
                    ]
                )

        # --------------------------------------------------------
        # Score
        # --------------------------------------------------------

        score, components = self._score(
            role_hits=role_hits,
            software_role_hits=software_role_hits,
            entry_title_hits=entry_title_hits,
            target_hits=target_hits,
            ai_hits=ai_hits,
            software_skill_hits=software_skill_hits,
            title_norm=title_norm,
            combined=combined,
            jd_exact_hits=jd_exact_hits,
            jd_exact_score=jd_exact_score,
        )

        # --------------------------------------------------------
        # Experience
        # --------------------------------------------------------

        (
            experience_score,
            experience_note,
            experience_ok,
        ) = self._experience_fit(
            title_norm,
            combined,
            title_experience_override=title_experience_override,
        )

        if not experience_ok:
            experience_mode = "hard_block"

        elif "Accepted entry-level" in experience_note:
            experience_mode = "zero_minimum"

        elif (
            "Fresher/entry-level" in experience_note
            or "No explicit" not in experience_note
        ):
            experience_mode = "entry_signal"

        elif "Stretch entry-level" in experience_note:
            experience_mode = "stretch_range"

        else:
            experience_mode = "unspecified"

        score = min(
            100,
            score + experience_score
        )

        # --------------------------------------------------------
        # Thresholds
        # --------------------------------------------------------

        threshold = int(
            self.config.get(
                "jd_match_threshold",
                55
            )
        )

        software_threshold = int(
            self.config.get(
                "software_match_threshold",
                max(
                    40,
                    threshold - 10
                )
            )
        )

        intern_threshold = int(
            self.config.get(
                "intern_match_threshold",
                max(
                    35,
                    threshold - 15
                )
            )
        )

        # --------------------------------------------------------
        # Tracks
        # --------------------------------------------------------

        is_ai_track = bool(
            role_hits
            or target_hits
            or ai_relevant
        )

        # This profile is configured for AI roles.  Generic software terms
        # ("Backend Developer", for example) are useful supporting evidence
        # for an AI posting, but must not independently opt the agent into an
        # unrelated job family merely because its resume has common software
        # skills.  A software title therefore needs AI/target-role evidence.
        is_software_track = bool(
            software_role_hits
            and (role_hits or ai_relevant)
        )

        is_entry_track = bool(
            entry_title_hits
        )

        # --------------------------------------------------------
        # Qualification
        # --------------------------------------------------------

        reasons = []

        hard_block = (
            hard_seniority_block
            or not experience_ok
        )

        if hard_seniority_block:
            reasons.append(
                f"seniority/title block: "
                f"{seniority_hit}"
            )

        if not experience_ok:
            reasons.append(
                experience_note
            )

        min_software_skills = int(
            self.config.get(
                "min_software_skill_hits",
                2
            )
        )

        min_intern_skills = int(
            self.config.get(
                "min_intern_skill_hits",
                1
            )
        )

        # --------------------------------------------------------
        # AI qualification
        # --------------------------------------------------------

        qualifies_ai = (
            not hard_block
            and is_ai_track
            and score >= threshold
            and len(jd_exact_hits) >= int(self.config.get("min_jd_exact_keyword_hits", 2))
            and (
                ai_relevant
                or bool(role_hits)
                or len(target_hits) >= 2
            )
        )

        # --------------------------------------------------------
        # Software qualification
        # --------------------------------------------------------

        qualifies_software = (
            not hard_block
            and is_software_track
            and len(software_skill_hits)
            >= min_software_skills
            and score >= software_threshold
            and len(jd_exact_hits) >= int(self.config.get("min_jd_exact_keyword_hits", 2))
        )

        # --------------------------------------------------------
        # Internship / entry qualification
        # --------------------------------------------------------

        qualifies_intern = (
            not hard_block
            and is_entry_track
            and len(software_skill_hits)
            >= min_intern_skills
            and score >= intern_threshold
            and len(jd_exact_hits) >= int(self.config.get("min_jd_exact_keyword_hits", 2))
            and (
                is_software_track
                or ai_relevant
                # A lone target-term hit is too broad: Python is a target
                # skill but does not make an otherwise generic junior web
                # role an AI-role match.  Require a configured target role,
                # an AI signal, or the already-gated software track.
                or bool(role_hits)
            )
        )

        eligible = bool(
            qualifies_ai
            or qualifies_software
            or qualifies_intern
        )

        # --------------------------------------------------------
        # Rejection diagnostics
        # --------------------------------------------------------

        if not eligible:

            if not (
                is_ai_track
                or is_software_track
                or is_entry_track
            ):
                reasons.append(
                    "title/content lacks a recognized "
                    "target, software, or entry-level track"
                )

            elif (
                is_software_track
                and len(software_skill_hits)
                < min_software_skills
            ):
                reasons.append(
                    f"only "
                    f"{len(software_skill_hits)} "
                    f"relevant software skill(s); "
                    f"need "
                    f"{min_software_skills}"
                )

            applicable_message_threshold = (
                threshold
                if not is_software_track
                else software_threshold
            )

            if score < applicable_message_threshold:
                reasons.append(
                    f"score {score} below "
                    f"applicable threshold"
                )

            if len(jd_exact_hits) < int(self.config.get("min_jd_exact_keyword_hits", 2)):
                reasons.append(
                    f"only {len(jd_exact_hits)} exact JD keyword hit(s); need "
                    f"{int(self.config.get('min_jd_exact_keyword_hits', 2))}"
                )

            if (
                is_ai_track
                and not ai_relevant
                and not is_software_track
            ):
                reasons.append(
                    "insufficient AI relevance "
                    "for AI-only track"
                )

        # --------------------------------------------------------
        # Track
        # --------------------------------------------------------

        if qualifies_ai:
            track = "ai"

        elif qualifies_software:
            track = "software"

        elif qualifies_intern:
            track = "intern"

        else:
            track = "none"

        # --------------------------------------------------------
        # RETURN
        #
        # Keep this structure exactly compatible with
        # naukri_agent.py.
        # --------------------------------------------------------

        return {
            "score": score,

            "threshold": threshold,

            "applicable_threshold": (
                threshold
                if track == "ai"
                else software_threshold
                if track == "software"
                else intern_threshold
            ),

            "eligible": eligible,

            "match_track": track,

            "matched_skills": matched,

            "missing_skills": missing,

            "role_hits": [
                self._display_role(x)
                for x in role_hits
            ],

            "software_role_hits":
                software_role_hits,

            "entry_title_hits":
                entry_title_hits,

            "target_skill_hits":
                target_hits,

            "software_skill_hits":
                software_skill_hits,

            "ai_signal_hits":
                ai_hits,

            "ai_relevant":
                ai_relevant,

            "role_relevant":
                bool(role_hits),

            "experience_ok":
                experience_ok,

            "experience_mode":
                experience_mode,

            "experience_note":
                experience_note,

            "seniority_block":
                seniority_hit,

            "rejection_reasons":
                reasons,

            "score_components": {
                **components,
                "experience":
                    experience_score,
            },

            "jd_exact_keyword_hits":
                jd_exact_hits,

            "jd_missing_keyword_hits":
                jd_exact_missing,

            "jd_exact_keyword_coverage":
                jd_exact["coverage_percent"],

            "jd_soft_skill_hits":
                jd_soft["matched"],

            "jd_soft_skill_missing":
                jd_soft["missing"],

            "jd_keyword_inventory":
                jd_keyword_inventory,
        }

    # ============================================================
    # SCORING
    # ============================================================

    def _score(
        self,
        *,
        role_hits,
        software_role_hits,
        entry_title_hits,
        target_hits,
        ai_hits,
        software_skill_hits,
        title_norm,
        combined,
        jd_exact_hits,
        jd_exact_score,
    ):

        preferred_role = (
            32
            if role_hits
            else 0
        )

        software_role = (
            22
            if software_role_hits
            else 0
        )

        entry_bonus = (
            6
            if entry_title_hits
            else 0
        )

        ai_bonus = min(
            12,
            len(ai_hits) * 3
        )

        target_bonus = min(
            25,
            len(target_hits) * 5
        )

        software_skill_bonus = min(
            25,
            len(software_skill_hits) * 5
        )

        score = (
            preferred_role
            + software_role
            + entry_bonus
            + ai_bonus
            + target_bonus
            + software_skill_bonus
            + jd_exact_score
        )

        return score, {
            "preferred_role":
                preferred_role,

            "software_role":
                software_role,

            "entry_title":
                entry_bonus,

            "ai_signal":
                ai_bonus,

            "target_skill":
                target_bonus,

            "software_skill":
                software_skill_bonus,

            "jd_exact_keyword":
                jd_exact_score,
        }

    # ============================================================
    # EXPERIENCE
    # ============================================================

    def _title_zero_minimum_range(self, title):
        """
        Return the upper bound when the Naukri job title explicitly
        contains a supported zero-minimum experience range, e.g.
        "0 to 2 years" / "0-2 years".

        This is intentionally title-only so unrelated JD-body numbers
        cannot override Naukri's experience metadata.
        """
        accepted_ranges = {
            str(x).strip().lower().replace(" ", "")
            for x in self.config.get(
                "accepted_entry_level_ranges",
                ["0-1", "0-2", "0-3"],
            )
        }

        pattern = re.compile(
            r"\b0\s*(?:to|-)\s*(\d+)\s*(?:years?|yrs?)\b",
            re.I,
        )

        for m in pattern.finditer(title):
            high = int(m.group(1))
            if f"0-{high}" in accepted_ranges:
                return high

        return None

    def _experience_fit(
        self,
        title,
        text,
        title_experience_override=None,
    ):

        cfg_max = int(
            self.config.get(
                "max_experience_years",
                3
            )
        )

        # --------------------------------------------------------
        # Senior title is a hard blocker.
        # --------------------------------------------------------

        senior_hit = self._first_title_term(
            title,
            self.config.get(
                "senior_title_terms",
                self.DEFAULT_SENIOR_TERMS
            )
        )

        if senior_hit:
            return (
                0,
                f"Senior/non-entry-level title "
                f"signal detected: {senior_hit}.",
                False,
            )

        # A Naukri title range such as "0 to 2 years of experience" is
        # authoritative job metadata. If it is a supported zero-minimum
        # range, accept it before parsing noisy JD-body numbers.
        if title_experience_override:
            high = title_experience_override
            if high <= cfg_max:
                return (
                    15,
                    "Fresher/entry-level or zero-experience "
                    "range detected from job title.",
                    True,
                )

        text = (
            text
            .replace("\u2013", "-")
            .replace("\u2014", "-")
            .replace("\u2212", "-")
        )

        # --------------------------------------------------------
        # Accepted zero-minimum ranges.
        #
        # ONLY these ranges are treated as valid numeric
        # entry-level ranges.
        #
        # 0-1
        # 0-2
        # 0-3
        # --------------------------------------------------------

        accepted_ranges = {
            str(x)
            .strip()
            .lower()
            .replace(" ", "")
            for x in self.config.get(
                "accepted_entry_level_ranges",
                [
                    "0-1",
                    "0-2",
                    "0-3",
                ]
            )
        }

        accepted = []
        accepted_spans = []

        zero_range_pattern = re.compile(
            r"\b0\s*(?:to|-)\s*"
            r"(\d+)\s*(?:years?|yrs?)\b",
            re.I,
        )

        for m in zero_range_pattern.finditer(text):

            high = int(
                m.group(1)
            )

            value = f"0-{high}"

            if (
                value in accepted_ranges
                and high <= cfg_max
            ):
                accepted.append(value)

                accepted_spans.append(
                    (
                        m.start(),
                        m.end()
                    )
                )

        # --------------------------------------------------------
        # Parse only genuine experience expressions.
        # --------------------------------------------------------

        requirements = self._experience_requirements(
            text,
            ignored_spans=accepted_spans
        )

        # --------------------------------------------------------
        # Any positive minimum is a hard blocker.
        # --------------------------------------------------------

        incompatible = []

        for r in requirements:

            if (
                r["lower"] > 0
                or r["upper"] > cfg_max
            ):
                incompatible.append(r)

        if incompatible:

            r = incompatible[0]

            if r["is_range"]:

                return (
                    0,
                    f"JD explicitly states "
                    f"{r['display']}; accepted "
                    f"experience is only 0-{cfg_max} "
                    f"years with a zero minimum.",
                    False,
                )

            return (
                0,
                f"JD explicitly requires at least "
                f"{r['display']}; candidate has 0 "
                f"professional years and only "
                f"zero-minimum entry-level roles "
                f"are accepted.",
                False,
            )

        # --------------------------------------------------------
        # Valid zero-minimum range.
        # --------------------------------------------------------

        if accepted:

            return (
                15,
                f"Fresher/entry-level or "
                f"zero-experience range detected.",
                True,
            )

        # --------------------------------------------------------
        # Explicit fresher language.
        # --------------------------------------------------------

        if re.search(
            r"\b(?:"
            r"fresher|"
            r"freshers|"
            r"entry[- ]level|"
            r"graduate trainee|"
            r"graduate engineer trainee|"
            r"new graduate|"
            r"recent graduate|"
            r"new grad|"
            r"no (?:prior\s+)?experience required|"
            r"without experience|"
            r"no experience required"
            r")\b",
            text,
            re.I,
        ):

            return (
                15,
                "Fresher/entry-level/"
                "no-experience language detected.",
                True,
            )

        # --------------------------------------------------------
        # No explicit positive minimum.
        # --------------------------------------------------------

        return (
            10,
            "No explicit mandatory >0-year "
            "experience requirement detected.",
            True,
        )

    # ============================================================
    # EXPERIENCE REQUIREMENT PARSER
    # ============================================================

    def _experience_requirements(
        self,
        text,
        ignored_spans=None,
    ):
        """
        Extract ONLY genuine experience requirements.

        Critical regression protection:

        Do NOT interpret arbitrary numbers in a JD as years.

        Bad examples that must NOT become experience:

            12 LPA
            12 months internship
            12 technologies
            2025
            12 employees
            12 openings
            12 skills

        Valid examples:

            2 years experience
            2+ years experience
            minimum 2 years experience
            at least 2 years experience
            2-5 years experience
            2 to 5 years experience
        """

        ignored_spans = ignored_spans or []

        found = []

        def ignored(m):

            return any(
                m.start() < end
                and m.end() > start
                for start, end in ignored_spans
            )

        # --------------------------------------------------------
        # Numeric ranges.
        #
        # Must contain "years"/"yrs".
        # --------------------------------------------------------

        range_spans = []

        range_pattern = re.compile(
            r"\b(\d+)\s*(?:to|-)\s*(\d+)"
            r"\s*(?:years?|yrs?)\b",
            re.I,
        )

        for m in range_pattern.finditer(text):

            if ignored(m):
                continue

            low = int(
                m.group(1)
            )

            high = int(
                m.group(2)
            )

            if high < low:
                low, high = high, low

            range_spans.append(
                (
                    m.start(),
                    m.end()
                )
            )

            found.append(
                {
                    "lower": low,
                    "upper": high,
                    "display": re.sub(
                        r"\s+",
                        " ",
                        m.group(0)
                    ).strip(),
                    "is_range": True,
                    "search_start": m.start(),
                }
            )

        # --------------------------------------------------------
        # Single-number experience requirements.
        #
        # Every pattern requires "experience" in the expression.
        # This is the protection against the previous false
        # "12 years" / unrelated-number bug.
        # --------------------------------------------------------

        patterns = [

            # minimum 2 years experience
            # at least 3 years experience
            # requires 2 years experience
            re.compile(
                r"\b(?:minimum|at least|required|"
                r"requires?|must have|must possess|"
                r"needs?|should have)\b"
                r"[^.\n]{0,50}?"
                r"\b(\d+)\s*\+?\s*"
                r"(?:years?|yrs?)"
                r"(?:\s+of)?\s+"
                r"(?:relevant\s+|"
                r"professional\s+|"
                r"hands[- ]on\s+|"
                r"industry\s+)?"
                r"experience\b",
                re.I,
            ),

            # 2+ years experience
            re.compile(
                r"\b(\d+)\s*\+\s*"
                r"(?:years?|yrs?)\s+"
                r"(?:of\s+)?"
                r"(?:relevant\s+|"
                r"professional\s+|"
                r"hands[- ]on\s+|"
                r"industry\s+)?"
                r"experience\b",
                re.I,
            ),

            # 2 years of experience
            re.compile(
                r"\b(\d+)\s*"
                r"(?:years?|yrs?)\s+"
                r"(?:of\s+)?"
                r"(?:relevant\s+|"
                r"professional\s+|"
                r"hands[- ]on\s+|"
                r"industry\s+)?"
                r"experience\b",
                re.I,
            ),

            # experience of 2 years
            re.compile(
                r"\bexperience\b"
                r"[^.\n]{0,30}?"
                r"\b(\d+)\s*"
                r"(?:years?|yrs?)\b",
                re.I,
            ),
        ]

        for pattern in patterns:

            for m in pattern.finditer(text):

                if ignored(m):
                    continue

                # ------------------------------------------------
                # Never duplicate a range.
                # ------------------------------------------------

                if any(
                    m.start() < end
                    and m.end() > start
                    for start, end in range_spans
                ):
                    continue

                matched_text = m.group(0).lower()

                # ------------------------------------------------
                # Final safety check.
                # ------------------------------------------------

                if "experience" not in matched_text:
                    continue

                value = int(
                    m.group(1)
                )

                found.append(
                    {
                        "lower": value,
                        "upper": value,
                        "display": re.sub(
                            r"\s+",
                            " ",
                            m.group(0)
                        ).strip(),
                        "is_range": False,
                        "search_start": m.start(),
                    }
                )

        # --------------------------------------------------------
        # Deduplicate.
        # --------------------------------------------------------

        unique = {}

        for item in found:

            key = (
                item["lower"],
                item["upper"],
                item["is_range"],
            )

            if key not in unique:
                unique[key] = item

        return list(
            unique.values()
        )

    # ============================================================
    # SKILL HELPERS
    # ============================================================

    def _contains_skill(
        self,
        text,
        skill,
    ):
        return self._contains_term_with_alias(
            text,
            skill
        )

    def _contains_term_with_alias(
        self,
        text,
        term,
    ):

        if self._contains_term(
            text,
            term
        ):
            return True

        for alias in self.aliases.get(
            term,
            []
        ):

            if self._contains_term(
                text,
                self._norm(alias)
            ):
                return True

        return False

    def _contains_term(
        self,
        text,
        term,
    ):

        if not term:
            return False

        if len(term) <= 4:

            return (
                re.search(
                    r"(?<![a-z0-9])"
                    + re.escape(term)
                    + r"(?![a-z0-9])",
                    text,
                )
                is not None
            )

        return term in text

    # ============================================================
    # ROLE MATCHING
    # ============================================================

    def _role_matches(
        self,
        title,
        role,
    ):

        if role in title:
            return True

        if role == "generative ai engineer":

            return (
                "genai engineer" in title
                or "generative ai" in title
            )

        if role == "ai/ml engineer":

            return (
                "ai ml engineer" in title
                or "ai engineer" in title
            )

        if role == "machine learning engineer":

            return (
                "ml engineer" in title
                or "machine learning engineer"
                in title
            )

        if role == "python ai engineer":

            return (
                "python engineer" in title
                and (
                    "ai" in title
                    or "ml" in title
                )
            )

        return False

    def _first_title_term(
        self,
        title,
        terms,
    ):

        for raw in terms:

            term = self._norm(raw)

            if (
                term
                and self._contains_term(
                    title,
                    term
                )
            ):
                return raw

        return None

    # ============================================================
    # DISPLAY HELPERS
    # ============================================================

    def _display_profile_or_term(
        self,
        norm,
    ):
        return self.skill_display.get(
            norm,
            norm
        )

    def _display_config_term(
        self,
        norm,
    ):

        for raw in (
            self.config.get(
                "skill_terms",
                []
            )
            + self.config.get(
                "ai_signal_terms",
                []
            )
        ):

            if self._norm(raw) == norm:
                return raw

        return norm

    def _display_role(
        self,
        role,
    ):

        for x in self.config.get(
            "primary",
            []
        ):

            if self._norm(x) == role:
                return x

        return role

    # ============================================================
    # NORMALIZATION
    # ============================================================

    def _norm(
        self,
        text,
    ):

        text = str(text).lower()

        text = text.replace(
            "&",
            " and "
        )

        text = text.replace(
            "\u2013",
            "-"
        )

        text = text.replace(
            "\u2014",
            "-"
        )

        text = text.replace(
            "\u2212",
            "-"
        )

        text = re.sub(
            r"[^a-z0-9+.#? -]+",
            " ",
            text
        )

        return re.sub(
            r"\s+",
            " ",
            text
        ).strip()
