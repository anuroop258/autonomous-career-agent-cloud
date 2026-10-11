"""Question-intent routing for job-application forms.

The router deliberately separates *what a field asks* from *how the browser
renders it*.  A text input can be a numeric experience question, a yes/no skill
question, or an open-ended question; the HTML widget alone cannot tell us.
"""
from __future__ import annotations

import re
from typing import Any, Iterable


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", norm(value)))


class QuestionIntentRouter:
    """Classify application questions conservatively.

    The key invariant is that the word ``experience`` alone never means
    ``experience_years``.  Duration needs an explicit numeric/time cue.
    """

    ACTION_WORDS = {
        "save", "continue", "next", "submit", "apply", "apply now", "send",
        "finish", "done", "skip", "back", "cancel", "review",
    }

    YES_NO_PREFIXES = (
        "do you ", "have you ", "are you ", "would you ", "will you ",
        "can you ", "could you ", "did you ", "is your ", "was your ",
        "were you ", "has your ", "will your ", "would your ",
    )

    OPENING_CUES = (
        "describe ", "tell us ", "tell me ", "explain ", "how would you ",
        "why do you ", "why are you ", "what interests you ",
        "what experience do you have", "describe your experience",
        "tell us about your experience", "describe your background",
    )

    DURATION_CUES = (
        "how many years", "how much experience", "years of experience",
        "year of experience", "years experience", "year experience",
        "number of years", "experience in years", "total years",
        "professional years", "years professionally", "experience (years)",
        "experience years", "exp years", "expyears", "experience_years",
    )

    @classmethod
    def route(
        cls,
        *,
        label: str = "",
        placeholder: str = "",
        aria_label: str = "",
        name: str = "",
        field_id: str = "",
        field_type: str = "",
        tag: str = "",
        role: str = "",
        context: str = "",
        options: Iterable[Any] | None = None,
    ) -> dict[str, Any]:
        label = str(label or "").strip()
        placeholder = str(placeholder or "").strip()
        aria_label = str(aria_label or "").strip()
        name = str(name or "").strip()
        field_id = str(field_id or "").strip()
        context = str(context or "").strip()
        opts = [str(x.get("text", "") if isinstance(x, dict) else x).strip() for x in (options or [])]
        opts = [x for x in opts if x and norm(x) not in cls.ACTION_WORDS]

        primary = " ".join(x for x in (label, aria_label, placeholder) if x)
        technical = " ".join(x for x in (name, field_id) if x)
        text = norm(primary or technical or context)
        all_text = norm(" ".join(x for x in (primary, technical, context) if x))

        option_norms = [norm(x) for x in opts]
        has_yes_no_options = bool(
            any(x in {"yes", "no"} for x in option_norms)
            or (
                any("yes" in x for x in option_norms)
                and any("no" in x for x in option_norms)
            )
        )
        explicit_yes_no = text.startswith(cls.YES_NO_PREFIXES)
        experience = "experience" in text or "hands-on" in text or "hands on" in text
        duration = any(cue in text for cue in cls.DURATION_CUES)
        numeric_option_pattern = any(
            bool(re.search(r"\b\d+\s*(?:-|to|–|—)\s*\d+\b", x, re.I))
            or bool(re.search(r"\b\d+\+\b", x))
            or bool(re.fullmatch(r"\d+(?:\.\d+)?", x))
            for x in opts
        )
        skill_cues = any(
            cue in text for cue in (
                "python", "java", "javascript", "typescript", "c++", "sql",
                "c#", "golang", "go ", "rust", "llm", "generative ai", "genai",
                "machine learning", "deep learning", "langchain", "rag", "fastapi",
                "tensorflow", "pytorch", "docker", "kubernetes", "aws", "azure", "gcp",
            )
        )

        # File controls are structural, not questions.
        if field_type == "file":
            return {"intent": "file_upload", "confidence": 1.0}

        # Explicit duration wins over generic experience.
        if duration and experience:
            return {"intent": "experience_years", "confidence": 1.0}
        if experience and numeric_option_pattern and not explicit_yes_no:
            return {"intent": "experience_years", "confidence": 0.93}

        # Skill/project yes/no questions must route to reasoning rather than
        # the numeric experience profile field.
        if experience and (explicit_yes_no or has_yes_no_options):
            if skill_cues:
                return {"intent": "skill_experience_yes_no", "confidence": 0.99}
            if "project" in text or "hands-on project" in text or "academic project" in text:
                return {"intent": "project_experience_yes_no", "confidence": 0.99}
            return {"intent": "experience_yes_no", "confidence": 0.96}

        # Explicit project-description questions are their own semantic class.
        # This prevents a saved "Experience and projects" answer from being
        # reused for unrelated project prompts through generic fuzzy matching.
        project_text_cues = (
            "what projects", "which projects", "your projects",
            "projects have you", "projects did you", "projects you have",
            "projects you built", "projects you developed", "describe your projects",
            "tell us about your projects", "tell me about your projects",
            "talk about your projects", "project portfolio",
            "projects or applications", "applications you have built",
            "applications you have developed", "explain the ai projects",
            "explain your projects", "briefly explain",
        )
        if "project" in text or "projects" in text:
            if any(cue in text for cue in project_text_cues) or text in {"projects", "project experience", "experience and projects"}:
                return {"intent": "project_text", "confidence": 0.99}

        # Open-ended experience should remain a reasoner field.
        if experience and any(cue in text for cue in cls.OPENING_CUES):
            return {"intent": "experience_text", "confidence": 0.99}
        if experience and any(
            cue in text for cue in (
                "describe", "tell", "explain", "background", "worked with",
                "hands-on", "hands on", "using", "used", "familiar with",
            )
        ):
            return {"intent": "open_text", "confidence": 0.90}

        # Generic yes/no fields with actual answer options should use the
        # reasoner only when there is no stronger deterministic profile field.
        if explicit_yes_no and has_yes_no_options:
            return {"intent": "yes_no", "confidence": 0.91}

        if tag == "textarea" or role in {"textbox", "combobox"}:
            if any(cue in text for cue in cls.OPENING_CUES):
                return {"intent": "open_text", "confidence": 0.97}

        if tag == "select" or role == "combobox":
            if opts:
                return {"intent": "single_select", "confidence": 0.80}

        # Keep technical names such as expYears deterministic when there is no
        # question wording available.
        compact = re.sub(r"[^a-z0-9]", "", technical.lower())
        if compact in {"expyears", "experienceyears", "totalexperienceyears"}:
            return {"intent": "experience_years", "confidence": 1.0}

        return {"intent": "unknown", "confidence": 0.45}


__all__ = ["QuestionIntentRouter"]
