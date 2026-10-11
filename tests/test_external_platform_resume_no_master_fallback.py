from pathlib import Path


def test_external_platforms_are_source_guarded():
    root = Path(__file__).resolve().parents[1]
    checks = {
        root / "naukri_agent.py": "job-specific tailored resume is unavailable; refusing generic resume.pdf fallback.",
        root / "platforms" / "indeed" / "indeed_agent.py": "job-specific tailored resume is unavailable; refusing generic resume.pdf fallback.",
        root / "platforms" / "linkedin" / "linkedin_agent.py": "job-specific tailored resume is unavailable; refusing generic resume.pdf fallback.",
    }
    for path, marker in checks.items():
        text = path.read_text(encoding="utf-8")
        assert marker in text


def test_common_upload_has_direct_and_file_chooser_routes():
    path = Path(__file__).resolve().parents[1] / "src" / "application" / "common" / "company_website_agent.py"
    text = path.read_text(encoding="utf-8")
    assert 'input[type=\'file\']' in text
    assert "expect_file_chooser" in text
    assert "resume_upload_target" in text
    assert "resume_uploaded" in text
