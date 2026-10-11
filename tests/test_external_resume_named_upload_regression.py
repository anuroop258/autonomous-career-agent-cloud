from pathlib import Path
from src.application.common.ai_form_engine import AIFormEngine

def test_ai_engine_can_disable_resume_upload():
    assert AIFormEngine(page=None, profile={}, enable_resume_upload=False).enable_resume_upload is False

def test_common_external_upload_has_named_button_and_selection():
    text=(Path(__file__).resolve().parents[1]/"src/application/common/company_website_agent.py").read_text()
    assert 're.compile(r"^upload\\s*resume$", re.I)' in text
    assert "resume_selected_by_name" in text

def test_linkedin_upload_uses_exact_upload_button_and_file_chooser():
    text=(Path(__file__).resolve().parents[1]/"platforms/linkedin/linkedin_agent.py").read_text()
    assert 'get_by_text("Upload resume", exact=True)' in text
    assert "expect_file_chooser" in text
    assert "RESUME SELECTED BY NAME" in text
