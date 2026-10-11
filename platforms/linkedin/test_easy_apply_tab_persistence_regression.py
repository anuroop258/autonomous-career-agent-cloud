from pathlib import Path
import json


def test_linkedin_native_easy_apply_tab_is_configured_to_remain_open():
    root = Path(__file__).resolve().parent
    cfg = json.loads((root / "linkedin_config.json").read_text(encoding="utf-8"))
    assert cfg.get("leave_native_apply_tab_open") is True
    assert cfg.get("leave_native_apply_tab_open_on_unresolved") is True


def test_process_job_keeps_native_tab_open_after_easy_apply_opens():
    src = (Path(__file__).resolve().parent / "linkedin_agent.py").read_text(encoding="utf-8")
    assert 'keep_tab_open = True' in src
    assert 'if not keep_tab_open:' in src
    assert 'LINKEDIN NATIVE APPLY TYPE' in src


def test_unresolved_native_question_leaves_tab_open():
    src = (Path(__file__).resolve().parent / "linkedin_agent.py").read_text(encoding="utf-8")
    assert 'await self._leave_native_tab_open(page, "unknown_question")' in src
    assert 'await self._leave_native_tab_open(page, "fill_failed")' in src


def test_linkedin_external_apply_source_and_destination_tabs_remain_open():
    src = (Path(__file__).resolve().parent / "linkedin_agent.py").read_text(encoding="utf-8")
    marker = 'if route == "external":'
    block = src.split(marker, 1)[1].split('if not await self.click_easy_apply(page):', 1)[0]
    assert 'keep_tab_open = True' in block
    assert 'external_page = await self.click_external_apply(context, page)' in block


def test_all_linkedin_application_routes_share_tab_preservation_guard():
    src = (Path(__file__).resolve().parent / "linkedin_agent.py").read_text(encoding="utf-8")
    assert 'keep_tab_open = False' in src
    assert 'keep_tab_open = True' in src
    assert 'if not keep_tab_open:' in src
