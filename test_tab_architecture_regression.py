from pathlib import Path

SRC = Path("naukri_agent.py").read_text(encoding="utf-8")

def test_only_new_pages_are_candidates_after_apply():
    assert "new_pages = [p for p in pages if p not in pages_before_apply" in SRC
    assert "non_naukri = []" not in SRC

def test_original_job_tab_is_not_closed_when_popup_opens():
    block = SRC[SRC.index("active = page"):SRC.index("try:\n                dest =", SRC.index("active = page"))]
    assert "original job-detail" in block
    assert "await page.close()" not in block

def test_apply_attempt_preserves_tab():
    assert "leave_page_open = True" in SRC
    assert "timeout=120" in SRC

def test_external_match_preserves_current_job_tab():
    marker = "if await self._native_apply_target_is_external(page):"
    block = SRC[SRC.index(marker):SRC.index("if self.native_jobs_found", SRC.index(marker))]
    assert "leave_page_open = True" in block
    assert "_click_external_apply_from_naukri" in block
    assert "fill_external_with_company_agent" in block

def test_live_applied_state_has_bounded_batched_reads():
    block = SRC[SRC.index("async def live_applied_state"):SRC.index("async def fill_external_with_company_agent")]
    assert "asyncio.wait_for(" in block
    assert "evaluate_all(" in block
    assert "timeout=4.0" in block
