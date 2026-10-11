from pathlib import Path


def test_external_engine_supports_submit_ctas_and_direct_application_urls():
    src = (Path(__file__).resolve().parents[1] / "src" / "application" / "common" / "company_website_agent.py").read_text(encoding="utf-8")
    low = src.lower()
    assert "submit application" in low
    assert "submit your application" in low
    assert "async def _application_context" in src
    assert "_looks_like_application_url" in src
    assert "[onclick]" in src


def test_linkedin_native_apply_accepts_plain_apply_label():
    src = (Path(__file__).resolve().parents[1] / "platforms" / "linkedin" / "linkedin_agent.py").read_text(encoding="utf-8")
    assert r're.fullmatch(r"apply(?:\s+now)?", text or "", re.I)' in src
    assert "successful click" in src.lower()


def test_linkedin_external_apply_uses_controlled_external_company_flow():
    src = (Path(__file__).resolve().parents[1] / "platforms" / "linkedin" / "linkedin_agent.py").read_text(encoding="utf-8")
    start = src.index('if route == "external":')
    end = src.index('if not await self.click_easy_apply(page):', start)
    block = src[start:end]
    assert 'click_external_apply(context, page)' in block
    assert 'fill_external_with_company_agent' in block
    assert 'external_apply_click_failed' in block
