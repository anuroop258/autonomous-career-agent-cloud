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


def test_indeed_stops_when_browser_cannot_verify_fill(monkeypatch):
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
    assert result == "fill_verification_failed"


def test_external_routes_use_company_form_automation():
    root = Path(__file__).resolve().parents[1]
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
    reasoner.gemini_key = "configured"
    reasoner.model_retries = 1
    reasoner.retry_backoff_seconds = 0.001
    attempts = []

    class Response:
        text = '{"answer":"ok"}'

    class Chat:
        def send_message(self, message):
            if len(attempts) == 0:
                attempts.append("first")
                raise RuntimeError("503 UNAVAILABLE high demand")
            attempts.append("second")
            return Response()

    class Chats:
        def create(self, model, config):
            return Chat()

    class Client:
        def __init__(self, api_key):
            self.chats = Chats()

    import sys, types
    google_mod = types.ModuleType("google")
    genai_mod = types.ModuleType("google.genai")
    types_mod = types.ModuleType("google.genai.types")
    genai_mod.Client = Client
    class GenerateContentConfig:
        def __init__(self, **kwargs): self.kwargs = kwargs
    types_mod.GenerateContentConfig = GenerateContentConfig
    google_mod.genai = genai_mod
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)
    monkeypatch.setattr(reasoner_module.time, "sleep", lambda _delay: None)

    assert reasoner._gemini_reason("unresolved", []) == {"answer":"ok"}
    assert attempts == ["first", "second"]


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


def test_external_company_job_detail_url_with_apply_cta_clicks_apply():
    import asyncio
    from src.application.common.company_website_agent import CompanyWebsiteAgent

    class DummyPage:
        url = "https://jobs.ea.com/en_US/careers/ApplicationMethods?jobId=214253"
        frames = []
        async def goto(self, *_args, **_kwargs):
            return None

    class Agent(CompanyWebsiteAgent):
        def load_profile(self): self.profile = {}
        async def record(self, *_args, **_kwargs): pass
        async def wait_for_page(self, _page): pass
        async def detect_blocker(self, _page): return None
        async def handle_cookie_consent(self, _page): return None
        async def _has_explicit_apply_cta(self, _page): return True
        async def click_apply(self, _page):
            self.clicked = True
            return True
        async def wait_for_application_form(self, _page, **_kwargs): return False

    page = DummyPage()
    agent = Agent()
    agent.clicked = False
    result = asyncio.run(agent.apply(page, page.url, application_opened=False))
    assert agent.clicked is True
    assert result["status"] == "FORM_NOT_READY"


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
    source = (Path(__file__).resolve().parents[1] / "platforms" / "indeed" / "indeed_agent.py").read_text(encoding="utf-8")
    assert "native Apply and form filling are allowed; final Submit remains blocked" in source
    assert 'status = "match_found_dry_run"' not in source


def test_indeed_single_job_debug_entrypoint_uses_existing_native_path_only():
    root = Path(__file__).resolve().parents[1]
    source = (root / "platforms" / "indeed" / "debug_single_job.py").read_text(encoding="utf-8")
    assert "agent.process_job(context, job_url)" in source
    assert "agent._run_external_company_flow" not in source
    assert "stopping without running external flow" in source
    assert "process_job -> direct_apply_control -> wait_for_application_ready -> run_application" in source
    assert "--force-native-debug" in source
    assert "agent.matcher.match" not in source
    assert "--force-native-debug" not in (root / "platforms" / "indeed" / "indeed_agent.py").read_text(encoding="utf-8")
    assert "--force-native-debug" not in (root / "platforms" / "indeed" / "application_engine.py").read_text(encoding="utf-8")


def test_indeed_prioritizes_a_discovered_linkedin_profile_field_before_unknown_dom_order():
    """A real label must reach the reasoner before generic page text can."""
    from platforms.indeed.indeed_agent import IndeedAgent

    class FieldRoutingProbe:
        next_unanswered_field = IndeedAgent.next_unanswered_field

        async def form_field_groups(self, _page):
            return [{"label": "Describe yourself", "kind": "text", "options": []}]

        async def _deterministic_form_field_fallback(self, _page):
            return {"label": "LinkedIn Profile *", "kind": "text", "options": []}

    field = asyncio.run(FieldRoutingProbe().next_unanswered_field(object()))
    assert field["label"] == "LinkedIn Profile *"
    answer = ProfileReasoner().reason(field["label"], field["options"])
    assert answer["answer"] == "https://www.linkedin.com/in/anuroop-kudire-b7a322268/"


def test_provider_failures_do_not_replace_form_question_with_page_text(monkeypatch):
    """Gemini/Ollama failures must not mutate the DOM-selected form question."""
    from platforms.indeed.indeed_agent import IndeedAgent

    class ProviderFailureAgent(IndeedAgent):
        def __init__(self):
            monkeypatch.setenv("DRY_RUN", "true")
            super().__init__()
            self.engine.reasoner.gemini_key = "configured"
            self.engine.reasoner.openai_key = ""
            self.engine.reasoner.ollama_enabled = True
            self.questions_seen = []
            self.filled_questions = []

        async def detect_blocker(self, page): return False
        async def get_job_text(self, page): return "Unrelated page sentence that must not become the question."
        def completed(self, body): return False
        async def next_unanswered_field(self, page):
            if self.questions_seen:
                return None
            return {"label": "Unsupported employer-specific field", "kind": "text", "options": []}
        async def current_question(self, page):
            raise AssertionError("current_question/page text must not replace next_unanswered_field label")
        async def fill_answer_in_panel(self, page, value, kind, question=None, options=None):
            self.filled_questions.append(question)
            return True
        async def verify_answer_in_panel(self, page, value, kind, question=None): return True
        async def wait_for_question_change(self, page, q, timeout_ms=4000): return False
        async def click_continue(self, page): return False

    agent = ProviderFailureAgent()

    def fail_gemini(question, options):
        agent.questions_seen.append(("gemini", question))
        raise HTTPError("https://gemini.test", 429, "quota", {}, io.BytesIO())

    def fail_ollama(question, options):
        agent.questions_seen.append(("ollama", question))
        raise HTTPError("http://127.0.0.1:11434/api/chat", 404, "not found", {}, io.BytesIO())

    monkeypatch.setattr(agent.engine.reasoner, "_gemini_reason", fail_gemini)
    monkeypatch.setattr(agent.engine.reasoner, "_ollama_reason", fail_ollama)

    result = asyncio.run(agent.run_application(object(), "https://example.test/job"))
    assert result == "unknown_question"
    assert agent.questions_seen == [
        ("gemini", "Unsupported employer-specific field"),
        ("ollama", "Unsupported employer-specific field"),
    ]
    assert agent.filled_questions == []


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
    root = Path(__file__).resolve().parents[1]
    for relative in ("platforms/indeed/naukri_agent.py", "platforms/linkedin/naukri_agent.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert "canonical_naukri_agent" in source
        assert "external_apply_skipped" not in source
    linkedin_form = (root / "platforms/linkedin/ai_form_engine.py").read_text(encoding="utf-8")
    assert "from src.application.common.ai_form_engine import AIFormEngine" in linkedin_form


def test_naukri_external_detection_is_a_handoff_route_not_a_skip():
    source = (Path(__file__).resolve().parents[1] / "naukri_agent.py").read_text(encoding="utf-8")
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
