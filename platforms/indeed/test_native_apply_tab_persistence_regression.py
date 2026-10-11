from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "platforms" / "indeed" / "indeed_agent.py").read_text(encoding="utf-8")


def test_native_apply_click_sets_application_opened_before_engine_runs():
    assert "application_opened = True" in SOURCE
    assert "await self.run_application(application_page, url)" in SOURCE


def test_native_apply_cleanup_has_a_hard_preserve_branch():
    marker = "# HARD NATIVE-APPLY SAFETY RULE:"
    assert marker in SOURCE
    block = SOURCE.split(marker, 1)[1]
    assert "if application_opened:" in block
    assert "elif status in application_states_to_keep_open:" in block
    preserve_segment = block.split("elif status in application_states_to_keep_open:", 1)[0]
    assert "await page.close()" not in preserve_segment


def test_common_partial_native_apply_failures_are_known_states():
    for status in (
        '"resume_upload_failed"',
        '"unknown_question"',
        '"form_discovery_failed"',
        '"no_questions"',
        '"application_error"',
    ):
        assert status in SOURCE
