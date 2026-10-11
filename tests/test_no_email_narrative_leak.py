import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.common.ai_form_engine import AIFormEngine
from src.application.common.company_website_agent import CompanyWebsiteAgent
from profile_reasoner import ProfileReasoner


def test_ai_engine_does_not_classify_message_type_email_as_email():
    engine = AIFormEngine(profile={})
    semantic = engine._classify(
        name="Contact-Message-Field-01",
        field_id="Contact-Message-Field-01",
        field_type="email",
        label="Message",
        placeholder="",
        aria_label="",
        tag="input",
        context="Email address is required for contact",
    )
    assert semantic != "email"


def test_ai_engine_does_not_classify_relevant_experience_email_input_as_email():
    engine = AIFormEngine(profile={})
    semantic = engine._classify(
        name="experience-message",
        field_id="experience-message",
        field_type="email",
        label="Tell us about your relevant Experience",
        placeholder="",
        aria_label="",
        tag="textarea",
        context="email contact",
    )
    assert semantic in {"message", "unknown", "bio"}
    assert semantic != "email"


def test_company_agent_rejects_bogus_email_type_on_message_field():
    agent = CompanyWebsiteAgent()
    semantic = agent.classify({
        "tag": "input",
        "type": "email",
        "name": "Contact-Message-Field-01",
        "id": "Contact-Message-Field-01",
        "label": "Message",
        "placeholder": "",
        "aria_label": "",
        "context": "Email address is required somewhere on the form",
    })
    assert semantic != "email"


def test_company_agent_rejects_bogus_email_type_on_experience_textarea():
    agent = CompanyWebsiteAgent()
    semantic = agent.classify({
        "tag": "textarea",
        "type": "email",
        "name": "relevant-experience",
        "id": "relevant-experience",
        "label": "Tell us about your relevant Experience",
        "placeholder": "",
        "aria_label": "",
        "context": "Contact email",
    })
    assert semantic != "email"


def test_reasoner_rejects_email_answer_for_message_question():
    reasoner = ProfileReasoner()
    result = reasoner._validate(
        {"answer": "anuroop954@gmail.com", "kind": "text", "confidence": 1.0},
        "Message",
        [],
    )
    assert result is None


def test_reasoner_accepts_email_only_for_email_question():
    reasoner = ProfileReasoner()
    result = reasoner._validate(
        {"answer": "anuroop954@gmail.com", "kind": "text", "confidence": 1.0},
        "Email Address",
        [],
    )
    assert result["answer"] == "anuroop954@gmail.com"


def test_legitimate_email_field_still_classifies_as_email():
    engine = AIFormEngine(profile={})
    semantic = engine._classify(
        name="contact-email-field-01",
        field_id="contact-email-field-01",
        field_type="email",
        label="Email",
        placeholder="Email address",
        aria_label="",
        tag="input",
        context="",
    )
    assert semantic == "email"


def test_company_agent_legitimate_email_field_still_classifies_as_email():
    agent = CompanyWebsiteAgent()
    semantic = agent.classify({
        "tag": "input",
        "type": "email",
        "name": "contact-email-field-01",
        "id": "contact-email-field-01",
        "label": "Email",
        "placeholder": "Email address",
        "aria_label": "",
        "context": "",
    })
    assert semantic == "email"
