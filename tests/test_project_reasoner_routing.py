import json
from pathlib import Path
import custom_qa_store
from profile_reasoner import ProfileReasoner


def test_project_question_uses_profile_not_fuzzy_custom_qa(tmp_path, monkeypatch):
    db = tmp_path / "qa.db"
    monkeypatch.setattr(custom_qa_store, "DB", db)
    custom_qa_store.save_custom_qa("Experience and projects", "PROJECT ANSWER")

    # Load the real profile from the project root so this test validates the
    # actual project-grounded answer path.
    root = Path(__file__).resolve().parents[1]
    reasoner = ProfileReasoner(base_dir=root)
    result = reasoner.reason("What are your projects?", options=[])

    assert result is not None
    assert result["field"] == "projects"
    assert result["answer"] != "PROJECT ANSWER"
    assert result["confidence"] == 1.0
