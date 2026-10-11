from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_linkedin_external_apply_uses_controlled_external_flow():
    src = (ROOT / "linkedin_agent.py").read_text(encoding="utf-8")
    block_start = src.index('if route == "external":')
    block_end = src.index('if not await self.click_easy_apply(page):', block_start)
    block = src[block_start:block_end]
    assert "click_external_apply(context, page)" in block
    assert "fill_external_with_company_agent" in block
    assert "external_apply_click_failed" in block
    assert "clicking and opening external application" in block
