from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_shine_files_replicated_and_entrypoint_exists():
    for name in ("storage.py", "profile.json", "role_config.json", "requirements.txt", "profile_reasoner.py", "qa_engine.py", "company_website_agent.py"):
        assert (ROOT / name).exists(), name
    assert (ROOT / "shine_agent.py").exists()
    assert (ROOT / "shine_main.py").exists()


def test_shine_ui_flow_contract():
    src = _read("shine_agent.py")
    assert "Skills/Roles" in src
    assert 'page.locator(\'input[placeholder="Enter Skills/Roles"]\')' in src
    assert 'page.locator(\'input[placeholder*="Skills/Roles" i]\')' in src
    assert 'get_by_placeholder(re.compile(r"Skills/Roles", re.I))' not in src
    assert "placeholder*=\"Location\"" in src
    assert "Search" in src
    assert "^Apply$" in src
    assert "^Applied$" in src
    assert "/jobs/" in src


def test_shine_persistent_dedup_is_post_discovery_only():
    src = _read("shine_agent.py")
    assert "if seen(self.db, url):" in src
    assert "mark_jobs_seen" not in src
    assert "job_history" not in src
    assert 'app(self.db, page.url' in src


def test_shine_does_not_bulk_mark_search_results():
    src = _read("shine_agent.py")
    assert "for candidate in candidates:" in src
    assert "mark_jobs_seen" not in src
    assert "job_history" not in src


def test_shine_backend_only_no_frontend_reference():
    src = _read("shine_main.py")
    assert "ShineAgent" in src
    assert "asyncio" in src
    assert "connect_over_cdp" in src
    assert "webapp" not in src.lower()


def test_shine_search_explicitly_selects_zero_year_experience():
    src = _read("shine_agent.py")
    assert "await self._select_fresher_experience(page)" in src
    assert "async def _select_fresher_experience" in src
    assert 'page.locator("select")' in src
    assert 'select_option(label=exact_zero' in src
    assert 'r"^0\\s*Yr$"' in src
    assert "Never choose by\n        option index" in src


def _shine_agent_class():
    import importlib.util

    path = ROOT / "shine_agent.py"
    spec = importlib.util.spec_from_file_location("shine_agent_regression", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.ShineAgent


def test_shine_job_url_contract_accepts_current_three_segment_detail_urls():
    ShineAgent = _shine_agent_class()

    assert ShineAgent._is_shine_job_url(
        "https://www.shine.com/jobs/ai-ml-engineer-genai-engineer-noida-india/novel-patterns/19392927"
    )
    assert ShineAgent._is_shine_job_url(
        "https://www.shine.com/jobs/some-role/some-company/12345?foo=bar"
    )


def test_shine_job_url_contract_rejects_search_and_unrelated_urls():
    ShineAgent = _shine_agent_class()

    assert not ShineAgent._is_shine_job_url(
        "https://www.shine.com/job-search/genai-ai-engineer-jobs?q=GenAI+Engineer"
    )
    assert not ShineAgent._is_shine_job_url(
        "https://www.shine.com/jobs/ai-ml-engineer-genai-engineer-noida-india"
    )
    assert not ShineAgent._is_shine_job_url(
        "https://example.com/jobs/role/company/12345"
    )


def test_shine_fresher_experience_parser_is_zero_minimum_and_max_three():
    ShineAgent = _shine_agent_class()

    assert ShineAgent._is_fresher_experience_eligible("0 to 1 Yrs")
    assert ShineAgent._is_fresher_experience_eligible("0 to 2 Yrs")
    assert ShineAgent._is_fresher_experience_eligible("0 to 3 Yrs")
    assert ShineAgent._is_fresher_experience_eligible("Freshers")
    assert ShineAgent._is_fresher_experience_eligible("0 Yr")

    assert not ShineAgent._is_fresher_experience_eligible("0 to 4 Yrs")
    assert not ShineAgent._is_fresher_experience_eligible("1 to 3 Yrs")
    assert not ShineAgent._is_fresher_experience_eligible("2 to 4 Yrs")
    assert not ShineAgent._is_fresher_experience_eligible("3 to 5 Yrs")
    assert not ShineAgent._is_fresher_experience_eligible("")


def test_shine_result_collection_prefilters_before_open_and_closes_rejected_tabs():
    src = _read("shine_agent.py")
    assert "_collect_job_candidates" in src
    assert "SHINE RESULT EXPERIENCE PREFILTER" in src
    assert "SHINE RESULT SKIP BEFORE OPEN" in src
    assert 'if not candidate["eligible_experience"]:' in src
    assert "job_page = await context.new_page()" in src
    assert "keep_open = False" in src
    assert "if not keep_open and not job_page.is_closed():" in src


def test_shine_result_experience_contract_uses_card_metadata_not_detail_page():
    src = _read("shine_agent.py")
    collector_start = src.index("async def _collect_job_candidates")
    collector_end = src.index("async def _collect_job_urls")
    collector = src[collector_start:collector_end]
    assert "job-card-line-text" in collector
    assert "eligible_experience" in collector
    assert "page.goto" not in collector
    assert "new_page" not in collector


def test_shine_current_search_caps_are_20_pages_and_2000_candidates():
    import json
    cfg = json.loads((ROOT / "role_config.json").read_text(encoding="utf-8"))
    assert cfg["max_search_pages_per_role"] == 20
    assert cfg["max_total_candidates"] == 2000


def test_shine_search_recovers_from_results_page_edit_search():
    src = _read("shine_agent.py")
    assert "Edit search" in src
    assert "dashboard/Edit search recovery" in src
    assert "_next_search_page_url" in src


def test_shine_application_flow_waits_before_marking_success():
    src = _read("shine_agent.py")
    assert "wait_for_destination" in src
    assert "wait_for_application_surface" in src
    assert "submission_unconfirmed" in src
