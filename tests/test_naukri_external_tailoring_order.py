from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_naukri_external_tailors_before_opening_company_site():
    text = (ROOT / "naukri_agent.py").read_text(encoding="utf-8")
    branch = text[text.index("if await self._native_apply_target_is_external(page):"):]
    tailor_pos = branch.index("build_tailored_resume(")
    click_pos = branch.index("_click_external_apply_from_naukri(page)")
    assert tailor_pos < click_pos
    assert "EXTERNAL APPLY BLOCKED" in branch
    assert "generic resume.pdf will NOT be used" in branch


def test_naukri_external_requires_existing_job_specific_resume():
    text = (ROOT / "naukri_agent.py").read_text(encoding="utf-8")
    assert 'self.current_resume_path = str(Path(str(tailored)).resolve())' in text
    assert 'external_resume_tailoring_failed' in text
    assert 'job-specific tailored resume is unavailable; refusing generic resume.pdf fallback.' in text
