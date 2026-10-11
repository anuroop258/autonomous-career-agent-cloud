from pathlib import Path

ROOT = Path(__file__).resolve().parent


def test_misdeclared_email_input_with_age_label_stays_age_semantic():
    from src.application.common.ai_form_engine import AIFormEngine
    engine = AIFormEngine(page=None, profile={"personal": {"email": "anuroop954@gmail.com"}})
    semantic = engine._classify(
        name="age", field_id="age", field_type="email", label="Age *",
        placeholder="", aria_label="", tag="input", context="Application form",
    )
    assert semantic == "age"


def test_explicit_email_field_still_classifies_as_email():
    from src.application.common.ai_form_engine import AIFormEngine
    engine = AIFormEngine(page=None, profile={"personal": {"email": "anuroop954@gmail.com"}})
    semantic = engine._classify(
        name="email", field_id="email", field_type="email", label="Email Address *",
        placeholder="Enter your email", aria_label="", tag="input", context="Application form",
    )
    assert semantic == "email"


def test_model_email_is_rejected_for_non_contact_question():
    from profile_reasoner import ProfileReasoner
    reasoner = ProfileReasoner(base_dir=ROOT)
    assert reasoner._validate(
        {"answer": "anuroop954@gmail.com", "kind": "text", "confidence": 1.0},
        "Tell us about your relevant experience", [],
    ) is None


def test_model_email_is_allowed_for_email_question():
    from profile_reasoner import ProfileReasoner
    reasoner = ProfileReasoner(base_dir=ROOT)
    result = reasoner._validate(
        {"answer": "anuroop954@gmail.com", "kind": "text", "confidence": 1.0},
        "What is your email address?", [],
    )
    assert result["answer"] == "anuroop954@gmail.com"


def test_message_question_does_not_accept_email_from_reasoner():
    import asyncio
    from src.application.common.ai_form_engine import AIFormEngine

    engine = AIFormEngine(page=None, profile={"personal": {"email": "anuroop954@gmail.com"}})

    class StubReasoner:
        def reason(self, question, options, context=None):
            return {"answer": "anuroop954@gmail.com", "kind": "text", "confidence": 1.0}

    engine.reasoner = StubReasoner()
    field = {
        "label": "Message", "question_context": "Message", "placeholder": "",
        "aria_label": "", "context": "", "semantic": "message", "options": [],
        "tag": "textarea", "type": "", "locator": None,
    }
    assert asyncio.run(engine._reason_and_fill(field)) is False
