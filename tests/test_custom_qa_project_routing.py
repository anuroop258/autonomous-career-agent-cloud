from pathlib import Path
import custom_qa_store


def _seed(tmp_path):
    custom_qa_store.DB = Path(tmp_path) / "qa.db"
    custom_qa_store.save_custom_qa("Experience and projects", "PROJECT ANSWER")


def test_projects_question_does_not_reuse_experience_and_projects_answer(tmp_path):
    _seed(tmp_path)
    result = custom_qa_store.find_custom_answer("What are your projects?")
    assert result is None


def test_projects_question_with_helper_text_does_not_reuse_saved_answer(tmp_path):
    _seed(tmp_path)
    result = custom_qa_store.find_custom_answer(
        "Please describe the projects you have built and the technologies you used"
    )
    assert result is None


def test_two_meaningful_tokens_can_still_match_long_helper_text(tmp_path):
    _seed(tmp_path)
    result = custom_qa_store.find_custom_answer(
        "Tell us about your experience and projects, including roles, internships, and work you are proud of"
    )
    assert result is not None
    assert result["answer"] == "PROJECT ANSWER"
