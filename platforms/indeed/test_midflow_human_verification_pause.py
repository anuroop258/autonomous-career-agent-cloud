from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "platforms" / "indeed" / "indeed_agent.py").read_text(encoding="utf-8")

def test_midflow_captcha_pauses_then_resumes_same_route():
    marker = 'BLOCKED MID-FLOW: CAPTCHA/OTP/security verification detected.'
    assert marker in SOURCE
    block = SOURCE.split(marker, 1)[1].split('body = await self.get_job_text(page)', 1)[0]
    assert 'pause_for_human_verification(page, "application")' in block
    assert 'continue' in block

def test_resume_edit_upload_steps_pause_for_human_verification():
    for scope in (
        "application-resume-edit",
        "application-cv-options",
        "application-upload",
        "application-upload-wait",
        "application-continue",
        "application-post-continue",
    ):
        assert f'pause_for_human_verification(page, "{scope}")' in SOURCE

def test_generic_captcha_widgets_are_detected_when_visible():
    assert 'iframe[title*="captcha" i]:visible' in SOURCE
    assert 'iframe[src*="captcha" i]:visible' in SOURCE
    assert '[class*="captcha" i]:visible' in SOURCE
    assert '[id*="captcha" i]:visible' in SOURCE


def test_pause_requires_explicit_dashboard_continue_signal():
    source = SOURCE
    start = source.index("async def pause_for_human_verification")
    block = source[start:source.index("    async def wait_stable", start)]
    assert "self._continue_requested()" in block
    assert "HUMAN VERIFICATION CLEARED — dashboard Enter/Continue received" in block
    assert "automatically resume" not in block.lower()
