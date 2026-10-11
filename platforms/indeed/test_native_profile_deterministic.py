import json
from pathlib import Path

from platforms.indeed.indeed_agent import IndeedAgent


PROFILE = json.loads(
    (Path(__file__).resolve().parents[2] / "profile.json").read_text(encoding="utf-8")
)


def test_native_profile_semantic_routes_working_profile_labels():
    expected = {
        "Phone No *": "phone",
        "Email *": "email",
        "City *": "city",
        "Current Company *": "current_company",
        "Current/Last drawn salary *": "current_ctc",
        "Expected annual salary *": "expected_ctc",
        "Total experience *": "total_experience",
        "Notice period *": "notice_period",
        "LinkedIn Profile *": "linkedin",
        "GitHub Profile *": "github",
        "Graduation year *": "graduation_year",
    }
    for label, semantic in expected.items():
        assert IndeedAgent._native_profile_semantic(label) == semantic


def test_native_profile_semantic_refuses_unverified_dob_and_age():
    assert IndeedAgent._native_profile_semantic("Age *") is None
    assert IndeedAgent._native_profile_semantic("Date of birth *") is None


def test_native_profile_values_match_verified_profile():
    class Stub:
        pass

    obj = Stub()
    obj.engine = Stub()
    obj.engine.reasoner = Stub()
    obj.engine.reasoner.profile = PROFILE
    values = IndeedAgent._native_deterministic_profile_values(obj)

    assert values["phone"] == "7032164500"
    assert values["email"] == "anuroop954@gmail.com"
    assert values["city"] == "Hyderabad"
    assert values["total_experience"] == "0"
    assert values["current_ctc"] == "0"
    assert values["last_drawn_salary"] == "0"
    assert values["expected_ctc"] == "400000"
    assert values["notice_period"] == "0"
    assert values["linkedin"].startswith("https://www.linkedin.com/in/")
    assert values["github"] == "https://github.com/anuroop258"


def test_native_profile_semantic_supports_salary_wording():
    assert IndeedAgent._native_profile_semantic("Current salary *") == "current_ctc"
    assert IndeedAgent._native_profile_semantic("Last drawn salary *") == "current_ctc"
    assert IndeedAgent._native_profile_semantic("Annual salary expectation *") == "expected_ctc"
    assert IndeedAgent._native_profile_semantic("Relevant experience *") == "total_experience"
