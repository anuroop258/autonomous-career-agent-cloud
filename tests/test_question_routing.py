from src.application.common.ai_form_engine import AIFormEngine
from src.application.common.question_router import QuestionIntentRouter


def test_experience_word_does_not_force_numeric_years():
    route = QuestionIntentRouter.route(label="Do you have hands-on experience with Python and Generative AI/LLMs?", options=["Yes", "No"])
    assert route["intent"] == "skill_experience_yes_no"


def test_numeric_experience_stays_years():
    route = QuestionIntentRouter.route(label="How many years of experience do you have in Python?")
    assert route["intent"] == "experience_years"


def test_open_ended_experience_routes_to_reasoner():
    route = QuestionIntentRouter.route(label="Describe your experience with Python and GenAI.")
    assert route["intent"] == "experience_text"


def test_engine_classification_avoids_experience_years_for_yes_no():
    engine = AIFormEngine(profile={})
    semantic = engine._classify(
        label="Do you have hands-on experience with Python and Generative AI/LLMs?",
        field_type="radio",
        tag="input",
        role="radio",
        options=[{"text": "Yes"}, {"text": "No"}],
    )
    assert semantic == "unknown"


def test_engine_classification_keeps_numeric_experience():
    engine = AIFormEngine(profile={})
    semantic = engine._classify(
        label="How many years of professional Python experience do you have?",
        field_type="text",
        tag="input",
    )
    assert semantic == "experience_years"


def test_engine_explicit_age_beats_surrounding_first_name_context():
    engine = AIFormEngine(profile={})
    semantic = engine._classify(
        name="age",
        field_id="age",
        label="Age *",
        context="First Name * Last Name *",
        field_type="text",
        tag="input",
    )
    assert semantic == "age"


def test_engine_explicit_position_beats_surrounding_first_name_context():
    engine = AIFormEngine(profile={})
    semantic = engine._classify(
        name="position",
        field_id="position",
        label="Position *",
        context="First Name * Last Name *",
        field_type="select",
        tag="select",
    )
    assert semantic == "job_role"
