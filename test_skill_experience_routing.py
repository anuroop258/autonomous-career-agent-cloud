import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from profile_reasoner import ProfileReasoner


def test_deep_learning_duration_is_numeric_fact_not_generic_generation():
    r = ProfileReasoner(base_dir=ROOT)
    out = r.reason(
        "How much experience do you have in Deep Learning?",
        [],
        {"widget": "textarea", "field_semantic": "unknown"},
    )
    assert out is not None
    assert out["kind"] == "number"
    assert out["answer"] == "0"
    assert out["field"] == "skill_experience_years.Deep Learning"


def test_python_duration_stays_numeric():
    r = ProfileReasoner(base_dir=ROOT)
    out = r.reason("How many years of experience do you have in Python?", [], {})
    assert out is not None
    assert out["kind"] == "number"
    assert out["answer"] == "0"
    assert out["field"] == "skill_experience_years.Python"


def test_generic_profile_summary_question_remains_generatable():
    r = ProfileReasoner(base_dir=ROOT)
    assert r._generation_task(
        "Tell us about your relevant experience",
        {"widget": "textarea", "field_semantic": "unknown"},
    ) == "open_ended_application_response"


def test_duration_task_is_not_open_ended_generation():
    r = ProfileReasoner(base_dir=ROOT)
    assert r._generation_task(
        "How much experience do you have in Deep Learning?",
        {"widget": "textarea", "field_semantic": "unknown"},
    ) == "skill_experience_years"
