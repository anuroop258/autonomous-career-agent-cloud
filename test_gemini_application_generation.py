import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from profile_reasoner import ProfileReasoner


class FakeGeminiReasoner(ProfileReasoner):
    def __init__(self):
        os.environ["ENABLE_GEMINI"] = "1"
        super().__init__(base_dir=ROOT)
        self.gemini_key = "test-key"

    def _gemini_available(self):
        return True

    def _gemini_reason(self, question, options, context=None):
        task = self._generation_task(question, context=context)
        if task == "professional_headline":
            return {
                "answer": "Generative AI | LLMs | RAG | Python | 2026 ECE Graduate",
                "kind": "text", "field": "generated.headline", "confidence": 1.0
            }
        if task == "professional_summary":
            return {
                "answer": "I am a 2026 ECE graduate with hands-on project experience in Generative AI, LLMs, RAG and Python. I built AI applications and automation projects and am seeking an entry-level opportunity.",
                "kind": "text", "field": "generated.summary", "confidence": 1.0
            }
        if task == "cover_letter":
            return {
                "answer": "I am a 2026 ECE graduate with hands-on project experience in Generative AI, RAG, Python and AI automation. I would be excited to contribute these skills in an entry-level role and continue learning with the team.",
                "kind": "text", "field": "generated.cover_letter", "confidence": 1.0
            }
        if task == "open_ended_application_response":
            return {
                "answer": "I am a fresher with hands-on project experience in Generative AI, RAG, Python and AI automation, and I am ready to contribute in an entry-level role.",
                "kind": "text", "field": "generated.open_ended", "confidence": 1.0
            }
        return None


def test_headline_routes_to_gemini_generation():
    r = FakeGeminiReasoner()
    out = r.reason("Headline", [], {"field_semantic": "headline", "widget": "easy_apply"})
    assert out and out["answer"]
    assert len(out["answer"]) <= 127
    assert out["field"] == "generated.headline"


def test_summary_routes_to_gemini_generation():
    r = FakeGeminiReasoner()
    with patch("profile_reasoner.find_custom_answer", return_value=None):
        out = r.reason("Summary", [], {"field_semantic": "summary", "widget": "textarea"})
    assert out and out["field"] == "generated.summary"


def test_cover_letter_routes_to_gemini_generation():
    r = FakeGeminiReasoner()
    out = r.reason("Cover letter", [], {"field_semantic": "cover_letter", "widget": "textarea"})
    assert out and out["field"] == "generated.cover_letter"


def test_generic_open_ended_routes_to_gemini_generation():
    r = FakeGeminiReasoner()
    out = r.reason("What makes you a good fit for this role?", [], {"field_semantic": "unknown", "widget": "textarea"})
    assert out and out["field"] == "generated.open_ended"


def test_generation_prompt_mentions_task_and_profile_grounding():
    r = FakeGeminiReasoner()
    system, user = r._prompt("Headline", [], {"field_semantic": "headline", "widget": "easy_apply"})
    assert "professional_headline" in user
    assert "maximum 127 characters" in system
    assert "ONLY the candidate profile" in system
