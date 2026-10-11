"""Cross-platform contracts for shared reasoning and safe form handling."""

from pathlib import Path

from profile_reasoner import ProfileReasoner


def test_profile_facts_and_experience_categories_are_truthful():
    reasoner = ProfileReasoner()

    cases = (
        ("Postal code", [], "500089"),
        ("PIN code", [], "500089"),
        ("Current city", [], "Hyderabad"),
        ("How many years of professional Python experience?", [], "0"),
        ("How many years of professional experience do you have?", [], "0"),
        ("Have you used Python?", ["Yes", "No"], "Yes"),
        ("Do you have project experience?", ["Yes", "No"], "Yes"),
        ("Is your CGPA below 7?", ["Yes", "No"], "Yes"),
        ("Select your CGPA", ["6-7", "7-8", "8-9", "9+"], "6-7"),
        ("Highest educational qualification", [], "B.E./B.Tech"),
        ("Expected salary", [], "4"),
        ("What are your current salary expectations?", [], "4"),
        ("LinkedIn Profile", [], "https://www.linkedin.com/in/anuroop-kudire-b7a322268/"),
        ("Are you authorized to work in India?", ["Yes", "No"], "Yes"),
        ("Do you require visa sponsorship?", ["Yes", "No"], "No"),
        ("Do you have certifications?", ["Yes", "No"], "Yes"),
        ("When can you join?", [], "Immediately"),
        ("Which programming languages do you know?", [], "Python, C++, Java, C"),
        ("What is your phone number?", [], "7032164500"),
        ("What is your email address?", [], "anuroop954@gmail.com"),
        ("What is your college name?", [], "Vasavi College of Engineering"),
        ("What is your specialization?", [], "Electronics and Communication Engineering"),
        ("Are you willing to sign an employment bond?", ["Yes", "No"], "No"),
    )

    for question, options, expected in cases:
        result = reasoner._local_reason(question, options)
        assert result is not None, question
        assert result["answer"] == expected, (question, result)


def test_unknown_personal_fact_remains_unresolved():
    # Do not invoke remote fallbacks in a regression test.  The deterministic
    # layer must make no unsupported personal claim on its own.
    assert ProfileReasoner()._local_reason("What is your father's profession?", []) is None


def test_catalog_fact_is_deterministic_and_does_not_need_gemini(monkeypatch):
    reasoner = ProfileReasoner()
    reasoner.gemini_key = "configured"
    monkeypatch.setattr(
        reasoner, "_gemini_reason",
        lambda *_args: (_ for _ in ()).throw(AssertionError("catalog answer must be local")),
    )
    result = reasoner.reason("What is your college name?", [])
    assert result["answer"] == "Vasavi College of Engineering"
    assert result["field"] == "education_details.college"


def test_platform_adapters_use_canonical_reasoning_and_company_engine():
    root = Path(__file__).resolve().parents[1]
    linkedin = (root / "platforms" / "linkedin" / "linkedin_agent.py").read_text(encoding="utf-8")
    indeed = (root / "platforms" / "indeed" / "indeed_agent.py").read_text(encoding="utf-8")

    assert "from src.application.common.profile_reasoner import ProfileReasoner" in linkedin
    assert "from src.application.common.company_website_agent import CompanyWebsiteAgent" in linkedin
    assert "from src.application.common.company_website_agent import CompanyWebsiteAgent" in indeed


def test_text_field_options_are_not_replaced_by_page_wide_labels():
    root = Path(__file__).resolve().parents[1]
    source = (root / "platforms" / "indeed" / "indeed_agent.py").read_text(encoding="utf-8")
    assert "next_field.get(\"options\") if next_field is not None" in source
    assert "else await self.visible_options(page)" in source
