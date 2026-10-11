import asyncio
import io
import json
import os
from pathlib import Path
from urllib.error import HTTPError

import profile_reasoner as reasoner_module

from profile_reasoner import ProfileReasoner


def _unresolved_question():
    return "Which supported application category applies?", ["Profile-backed", "Unsupported"]


def test_gemini_key_is_environment_only(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "environment-key")
    reasoner = ProfileReasoner()
    assert reasoner.gemini_key == "environment-key"
    assert not Path("GEMINI_KEY.txt").exists()


def test_deterministic_answer_does_not_call_gemini(monkeypatch):
    reasoner = ProfileReasoner()
    reasoner.gemini_key = "configured"
    called = False

    def unexpected(*_args):
        nonlocal called
        called = True
        raise AssertionError("Gemini must not run for a deterministic fact")

    monkeypatch.setattr(reasoner, "_gemini_reason", unexpected)
    assert reasoner.reason("Postal code", [])["answer"] == "500089"
    assert called is False


def test_invalid_gemini_option_uses_validated_ollama_fallback(monkeypatch):
    reasoner = ProfileReasoner()
    reasoner.gemini_key = "configured"
    reasoner.openai_key = ""
    reasoner.ollama_enabled = True
    question, options = _unresolved_question()
    monkeypatch.setattr(reasoner, "_gemini_reason", lambda *_: {
        "answer": "Invented option", "kind": "single_select"
    })
    monkeypatch.setattr(reasoner, "_ollama_reason", lambda *_: {
        "answer": "Profile-backed", "kind": "single_select"
    })
    assert reasoner.reason(question, options)["answer"] == "Profile-backed"


def test_gemini_timeout_uses_ollama_fallback(monkeypatch):
    reasoner = ProfileReasoner()
    reasoner.gemini_key = "configured"
    reasoner.openai_key = ""
    reasoner.ollama_enabled = True
    question, options = _unresolved_question()
    monkeypatch.setattr(reasoner, "_gemini_reason", lambda *_: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(reasoner, "_ollama_reason", lambda *_: {
        "answer": "Profile-backed", "kind": "single_select"
    })
    assert reasoner.reason(question, options)["answer"] == "Profile-backed"


def test_all_invalid_model_answers_fail_safely(monkeypatch):
    reasoner = ProfileReasoner()
    reasoner.gemini_key = "configured"
    reasoner.openai_key = "configured"
    reasoner.ollama_enabled = True
    question, options = _unresolved_question()
    invalid = {"answer": "Invented option", "kind": "single_select"}
    monkeypatch.setattr(reasoner, "_gemini_reason", lambda *_: invalid)
    monkeypatch.setattr(reasoner, "_ollama_reason", lambda *_: invalid)
    monkeypatch.setattr(reasoner, "_openai_reason", lambda *_: invalid)
    assert reasoner.reason(question, options) is None


def test_indeed_does_not_abort_when_browser_recheck_cannot_verify_fill(monkeypatch):
    from platforms.indeed.indeed_agent import IndeedAgent

    class VerificationFailureAgent(IndeedAgent):
        def __init__(self):
            os.environ["DRY_RUN"] = "true"
            super().__init__()

        async def detect_blocker(self, page): return False
        async def get_job_text(self, page): return "application form"
        def completed(self, body): return False
        async def next_unanswered_field(self, page):
            return {"label": "Postal code", "options": [], "kind": "text"}
        async def fill_answer_in_panel(self, *args, **kwargs): return True
        async def verify_answer_in_panel(self, *args, **kwargs): return False

    result = asyncio.run(VerificationFailureAgent().run_application(object(), "https://example.test/job"))
    assert result != "fill_verification_failed"


def test_external_routes_use_company_form_automation():
    root = Path(__file__).resolve().parents[2]
    indeed = (root / "platforms" / "indeed" / "indeed_agent.py").read_text(encoding="utf-8")
    linkedin = (root / "platforms" / "linkedin" / "linkedin_agent.py").read_text(encoding="utf-8")
    naukri = (root / "naukri_agent.py").read_text(encoding="utf-8")
    assert "_run_external_company_flow" in indeed
    assert "APPLY ON COMPANY SITE CLICKED" in indeed
    assert "click_external_apply" in linkedin
    assert "fill_external_with_company_agent" in linkedin
    assert "_click_external_apply_from_naukri" in naukri
    assert "fill_external_with_company_agent" in naukri
    assert "EXTERNAL/COMPANY-SITE APPLY DETECTED — not clicked or filled" not in indeed
    assert "EXTERNAL/COMPANY-SITE APPLY DETECTED — not clicked or filled" not in linkedin


def test_salary_intent_variants_remain_disambiguated():
    reasoner = ProfileReasoner()
    current = (
        "current salary", "current ctc", "current compensation", "current package",
    )
    expected = (
        "expected salary", "salary expectations", "expected ctc", "desired compensation",
        "What are your current salary expectations?",
    )
    for question in current:
        result = reasoner._local_reason(question, [])
        assert result["field"] == "compensation.current_ctc", (question, result)
        assert result["answer"] == "0", (question, result)
    for question in expected:
        result = reasoner._local_reason(question, [])
        assert result["field"] == "compensation.expected_ctc", (question, result)
        assert result["answer"] == "4", (question, result)


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self): return json.dumps(self.payload).encode("utf-8")


def test_gemini_503_retries_with_bounded_backoff(monkeypatch):
    reasoner = ProfileReasoner()
    reasoner.model_retries = 1
    reasoner.retry_backoff_seconds = 0.001
    attempts = []

    def urlopen(_req, timeout):
        attempts.append(timeout)
        if len(attempts) == 1:
            raise HTTPError("https://gemini.test", 503, "unavailable", {}, io.BytesIO())
        return _FakeResponse({"candidates": [{"content": {"parts": [{"text": '{"answer":"ok"}'}]}}]})

    monkeypatch.setattr(reasoner_module.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(reasoner_module.time, "sleep", lambda _delay: None)
    assert reasoner._gemini_reason("unresolved", []) == {"answer": "ok"}
    assert len(attempts) == 2


def test_ollama_404_uses_generate_compatibility_once(monkeypatch):
    reasoner = ProfileReasoner()
    reasoner.model_retries = 0
    calls = []

    def urlopen(req, timeout):
        calls.append(req.full_url)
        if req.full_url.endswith("/api/chat"):
            raise HTTPError(req.full_url, 404, "not found", {}, io.BytesIO())
        return _FakeResponse({"response": '{"answer":"fallback"}'})

    monkeypatch.setattr(reasoner_module.urllib.request, "urlopen", urlopen)
    assert reasoner._ollama_reason("unresolved", [])["answer"] == "fallback"
    assert calls == ["http://127.0.0.1:11434/api/chat", "http://127.0.0.1:11434/api/generate"]


def test_external_handoff_uses_existing_page_without_second_apply_click(monkeypatch):
    from src.application.common.company_website_agent import CompanyWebsiteAgent

    class ExistingPage:
        url = "https://careers.example.test/apply"
        async def goto(self, *_args, **_kwargs):
            raise AssertionError("existing external application page must not reload")

    class HandoffAgent(CompanyWebsiteAgent):
        def load_profile(self): self.profile = {}
        async def record(self, *_args, **_kwargs): pass
        async def wait_for_page(self, _page): pass
        async def detect_blocker(self, _page): return None
        async def click_apply(self, _page): raise AssertionError("external CTA was already clicked")
        async def handle_cookie_consent(self, _page): return None
        async def wait_for_application_form(self, _page, **_kwargs): return False

    result = asyncio.run(HandoffAgent().apply(ExistingPage(), ExistingPage.url, application_opened=True))
    assert result["status"] == "FORM_NOT_READY"


def test_indeed_dry_run_exercises_apply_and_blocks_only_final_submit():
    source = (Path(__file__).resolve().parents[2] / "platforms" / "indeed" / "indeed_agent.py").read_text(encoding="utf-8")
    assert "native Apply and form filling are allowed; final Submit remains blocked" in source
    assert 'status = "match_found_dry_run"' not in source


def test_indeed_operator_caps_cannot_expand_a_supervised_run(monkeypatch):
    from platforms.indeed.indeed_agent import IndeedAgent

    monkeypatch.setenv("MAX_JOBS", "1")
    monkeypatch.setenv("MAX_APPLICATIONS", "1")
    agent = IndeedAgent()
    assert agent.max_total_candidates == 1
    assert agent.target_direct_applications == 1

    monkeypatch.setenv("MAX_JOBS", "not-a-number")
    monkeypatch.setenv("MAX_APPLICATIONS", "0")
    agent = IndeedAgent()
    assert agent.max_total_candidates == agent.cfg["max_total_candidates"]
    assert agent.target_direct_applications == agent.cfg["target_direct_applications"]


def test_compatibility_adapters_cannot_reintroduce_external_skip_logic():
    root = Path(__file__).resolve().parents[2]
    for relative in ("platforms/indeed/naukri_agent.py", "platforms/linkedin/naukri_agent.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert "canonical_naukri_agent" in source
        assert "external_apply_skipped" not in source
    linkedin_form = (root / "platforms/linkedin/ai_form_engine.py").read_text(encoding="utf-8")
    assert "from src.application.common.ai_form_engine import AIFormEngine" in linkedin_form


def test_naukri_external_detection_is_a_handoff_route_not_a_skip():
    source = (Path(__file__).resolve().parents[2] / "naukri_agent.py").read_text(encoding="utf-8")
    assert 'status = "external_skipped"' not in source
    assert "SKIPPED EXTERNAL" not in source
    assert "Native-only: never click" not in source
    assert "handed to the canonical CompanyWebsiteAgent" in source


def test_validated_gemini_answer_reaches_the_canonical_form_filler(monkeypatch):
    """Exercise question -> Gemini result -> validated option -> field action."""
    from src.application.common.ai_form_engine import AIFormEngine

    reasoner = ProfileReasoner()
    reasoner.gemini_key = "configured-for-test"
    reasoner.ollama_enabled = False
    reasoner.openai_key = ""
    question, options = _unresolved_question()
    monkeypatch.setattr(reasoner, "_gemini_reason", lambda *_: {
        "answer": "Profile-backed",
        "kind": "single_select",
        "selected_options": ["Profile-backed"],
        "field": "candidate.test",
        "confidence": 0.95,
    })

    engine = AIFormEngine()
    engine.reasoner = reasoner
    selected = []

    async def capture_select(_locator, value):
        selected.append(value)
        return True

    monkeypatch.setattr(engine, "_select_value", capture_select)
    field = {
        "semantic": "unknown",
        "label": question,
        "options": [{"text": option} for option in options],
        "tag": "select",
        "locator": object(),
    }
    assert asyncio.run(engine._reason_and_fill(field)) is True
    assert selected == ["Profile-backed"]
    assert engine.fallback_fields_filled == 1


def test_indeed_form_discovery_is_label_driven_not_page_text_driven():
    source = (Path(__file__).resolve().parents[2] / "platforms" / "indeed" / "indeed_agent.py").read_text(encoding="utf-8")
    assert "async def form_field_groups(self, page):" in source
    assert "_field_group_label(el)" in source
    assert 'q = next_field["label"] if next_field else await self.current_question(page)' in source


def test_indeed_form_groups_match_reference_top_level_field_model():
    source = (Path(__file__).resolve().parents[2] / "platforms" / "indeed" / "indeed_agent.py").read_text(encoding="utf-8")
    block = source.split("    async def form_field_groups(self, page):", 1)[1].split("    async def ", 1)[0]
    assert '"frame_index": self._frame_index(page, frame)' not in block
    assert "for frame in await self._form_frames(page)" not in block


def test_indeed_no_answerable_field_falls_through_to_native_flow_state():
    source = (Path(__file__).resolve().parents[2] / "platforms" / "indeed" / "indeed_agent.py").read_text(encoding="utf-8")
    assert 'q = next_field["label"] if next_field else await self.current_question(page)' in source
    assert 'return "no_form_field"' not in source
