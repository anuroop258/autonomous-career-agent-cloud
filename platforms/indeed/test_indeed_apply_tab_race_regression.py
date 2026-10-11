from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "platforms" / "indeed" / "indeed_agent.py").read_text(encoding="utf-8")


def test_native_apply_waits_for_real_application_target_before_form_engine():
    assert "_wait_for_native_application_target" in SOURCE
    block = SOURCE.split("application_page = await self._wait_for_native_application_target", 1)[1]
    assert 'status = "application_transition_timeout"' in block
    assert 'await self.run_application(application_page, url)' in block


def test_new_tab_wait_ignores_about_blank_and_same_job_page():
    helper = SOURCE.split("async def _wait_for_native_application_target", 1)[1].split(
        "async def wait_for_application_ready", 1
    )[0]
    assert 'candidate_url.lower() == "about:blank"' in helper
    assert 'if u == o:' in helper
    assert "APPLICATION TAB OPENED BUT NOT READY" in helper or "NATIVE APPLICATION TAB/STATE NOT DETECTED AFTER WAIT" in helper


def test_apply_job_page_apply_cta_is_not_a_ready_signal():
    helper = SOURCE.split("async def _wait_for_native_application_target", 1)[1].split(
        "async def wait_for_application_ready", 1
    )[0]
    assert "Do not accept the ordinary job-page Apply CTA" in helper or "Do not accept the ordinary job-page Apply CTA or generic" in helper
    assert 'r"resume|cv options|continue|next|review|submit' in helper


def test_indeed_beta_apply_redirect_shell_is_not_application_ready():
    helper = SOURCE.split("async def _wait_for_native_application_target", 1)[1].split(
        "async def wait_for_application_ready", 1
    )[0]
    assert "_is_indeed_redirect_shell" in helper
    assert "/beta/indeedapply/form/" in helper
    assert "candidate_url = (candidate.url or \"\").strip()" in helper
    assert "Re-read after the shell's JS redirect" in helper


def test_stale_pre_redirect_url_is_re_read_after_load():
    helper = SOURCE.split("async def _wait_for_native_application_target", 1)[1].split(
        "async def wait_for_application_ready", 1
    )[0]
    assert "URL may have changed during DOMContentLoaded/redirect" in helper
    assert "_looks_like_application_url(candidate_url, source_url)" in helper
