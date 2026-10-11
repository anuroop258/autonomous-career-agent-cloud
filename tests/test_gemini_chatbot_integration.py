import os
from pathlib import Path

import profile_reasoner as reasoner_module
from profile_reasoner import ProfileReasoner


def test_default_gemini_model_matches_working_chatbot(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    reasoner = ProfileReasoner()
    assert reasoner.gemini_model == "gemini-3.5-flash-lite"


def test_gemini_environment_file_is_loaded_without_overwriting_process_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=file-key\nGEMINI_MODEL=gemini-3.5-flash-lite\n", encoding="utf-8")
    monkeypatch.setenv("GEMINI_ENV_FILE", str(env_file))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    reasoner = ProfileReasoner()
    assert reasoner.gemini_key == "file-key"
    assert reasoner.gemini_model == "gemini-3.5-flash-lite"


def test_gemini_sdk_path_uses_chatbot_style_client(monkeypatch):
    reasoner = ProfileReasoner()
    reasoner.gemini_key = "configured"
    calls = []

    class Response:
        text = '{"answer":"Profile-backed","kind":"single_select","confidence":0.95}'

    class Chat:
        def send_message(self, message):
            calls.append(("send_message", message))
            return Response()

    class Chats:
        def create(self, model, config):
            calls.append(("create", model, config))
            return Chat()

    class FakeClient:
        def __init__(self, api_key):
            calls.append(("client", api_key))
            self.chats = Chats()

    class FakeGenai:
        Client = FakeClient

    class FakeTypes:
        class GenerateContentConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    # Import resolution needs google.genai and google.genai.types as modules.
    import types, sys
    google_mod = types.ModuleType("google")
    genai_mod = types.ModuleType("google.genai")
    types_mod = types.ModuleType("google.genai.types")
    genai_mod.Client = FakeClient
    types_mod.GenerateContentConfig = FakeTypes.GenerateContentConfig
    google_mod.genai = genai_mod
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)

    result = reasoner._gemini_reason("Which supported application category applies?", ["Profile-backed", "Unsupported"])
    assert result["answer"] == "Profile-backed"
    assert calls[0] == ("client", "configured")
    assert calls[1][0] == "create"
    assert calls[1][1] == "gemini-3.5-flash-lite"
    assert calls[2][0] == "send_message"


def test_platform_launchers_no_longer_force_disable_gemini():
    root = Path(__file__).resolve().parents[1]
    for rel in [
        "naukri_main.py",
        "platforms/indeed/indeed_main.py",
        "platforms/linkedin/linkedin_main.py",
        "platforms/glassdoor/glassdoor_main.py",
    ]:
        source = (root / rel).read_text(encoding="utf-8")
        assert 'ENABLE_GEMINI"] = "0"' not in source
        assert 'setdefault("ENABLE_GEMINI", "0")' not in source


# ---- unknown-question connection tests -------------------------------------
def _reasoner(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "real-looking-key")
    monkeypatch.delenv("ENABLE_GEMINI", raising=False)
    r = ProfileReasoner()
    r.ollama_enabled = False
    r.openai_key = ""
    return r


def test_placeholder_key_is_treated_as_unconfigured(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "PASTE_YOUR_GEMINI_API_KEY_HERE")
    assert ProfileReasoner().gemini_key == ""


def test_unknown_question_reaches_gemini_and_missing_confidence_is_accepted(monkeypatch):
    r = _reasoner(monkeypatch)
    calls = []

    def fake(question, options, context=None):
        calls.append(question)
        return {"answer": "Hands-on with LLM APIs through projects.", "kind": "text"}

    r._gemini_reason = fake
    q = "Zzqx unmapped employer specific prompt about collaboration style"
    out = r.reason(q, [])
    assert out and out["answer"].startswith("Hands-on")
    assert out["confidence"] >= 0.65  # engines reject < 0.65
    # repeated question is served from cache, not a second API call
    r.reason(q, [])
    assert len(calls) == 1


def test_missing_kind_with_options_is_resolved_to_visible_option(monkeypatch):
    r = _reasoner(monkeypatch)
    r._gemini_reason = lambda q, o, context=None: {"answer": "b) beta", "selected_options": ["Beta"]}
    out = r.reason("Zzqx pick a flavour of unmapped thing", ["Alpha", "Beta"])
    assert out and out["answer"] == "Beta"


def test_null_and_low_confidence_answers_are_rejected(monkeypatch):
    r = _reasoner(monkeypatch)
    assert r._validate({"answer": "null", "kind": "text"}, "q", []) is None
    assert r._validate({"answer": "x", "kind": "text", "confidence": 0.2}, "q", []) is None


def test_permanent_gemini_errors_disable_provider_for_session(monkeypatch):
    r = _reasoner(monkeypatch)
    n = {"c": 0}

    def boom(question, options, context=None):
        n["c"] += 1
        raise RuntimeError("400 API key not valid. Please pass a valid API key.")

    r._gemini_reason = boom
    r.reason("Zzqx first unmapped question", [])
    r.reason("Zzqx second unmapped question", [])
    assert n["c"] == 1
    assert r._gemini_disabled_reason


def test_company_fill_no_longer_forces_gemini_off():
    src = (Path(__file__).resolve().parents[1] / "company_fill.py").read_text(encoding="utf-8")
    assert 'os.environ["ENABLE_GEMINI"] = "0"' not in src
