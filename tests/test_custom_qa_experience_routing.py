import tempfile
from pathlib import Path

import custom_qa_store
from src.application.common.ai_form_engine import AIFormEngine


def _seed_db(tmp_path):
    custom_qa_store.DB = Path(tmp_path) / "qa.db"
    custom_qa_store.save_custom_qa("Experience and projects", "PROJECT ANSWER")


def test_generic_experience_does_not_match_projects_answer(tmp_path):
    _seed_db(tmp_path)
    result = custom_qa_store.find_custom_answer(
        "Relevant AI experience*",
        options=["Less than 1 year", "1-2 years", "2-3 years", "3+ years"],
    )
    assert result is None


def test_exact_experience_and_projects_label_still_matches(tmp_path):
    _seed_db(tmp_path)
    result = custom_qa_store.find_custom_answer("Experience and projects*")
    assert result is not None
    assert result["answer"] == "PROJECT ANSWER"


def test_native_experience_select_is_not_open_ended_reasoner_question():
    engine = AIFormEngine.__new__(AIFormEngine)
    from src.application.common.question_router import QuestionIntentRouter
    engine.question_router = QuestionIntentRouter()
    semantic = engine._classify(
        name="experience_level",
        field_id="career-experience_level",
        field_type="select-one",
        label="Relevant AI experience*",
        tag="select",
        options=["Less than 1 year", "1-2 years"],
    )
    assert semantic == "experience"


def test_project_text_is_reasoner_owned():
    from src.application.common.ai_form_engine import AIFormEngine
    engine = AIFormEngine.__new__(AIFormEngine)
    from src.application.common.question_router import QuestionIntentRouter
    engine.question_router = QuestionIntentRouter()
    semantic = engine._classify(
        name="projects",
        field_id="project-description",
        field_type="text",
        label="What are your projects?",
        tag="textarea",
        options=[],
    )
    assert semantic == "unknown"
