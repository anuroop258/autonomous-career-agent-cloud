from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_timesjobs_required_files_exist():
    for name in (
        "storage.py", "profile.json", "role_config.json", "requirements.txt",
        "profile_reasoner.py", "qa_engine.py", "company_website_agent.py",
        "timesjobs_agent.py", "timesjobs_main.py", "README.md"
    ):
        assert (ROOT / name).exists(), name


def test_timesjobs_ui_contract_matches_recording():
    src = read("timesjobs_agent.py")
    assert 'HOME = f"{BASE}/myHome"' in src
    assert "Enter Skills, Designation, etc" in src
    assert "Enter locations" in src
    assert "Let's Find" in src
    assert "job-detail" in src
    assert "ApplicationFlow.find_apply" in src
    assert "TIMESJOBS EXTERNAL APPLY" in src
    assert "HCLTech" not in src  # do not hard-code one company from the recording


def test_timesjobs_persistent_dedup_is_post_discovery_only():
    src = read("timesjobs_agent.py")
    assert "if seen(self.db, url):" in src
    assert "mark_jobs_seen" not in src
    assert "job_history" not in src
    assert 'app(self.db, page.url' in src


def test_timesjobs_no_unlimited_feature():
    src = read("timesjobs_agent.py")
    cfg = read("role_config.json")
    assert "AgentLimits" not in src
    assert "Unlimited" not in src
    assert "job_history" not in src
    assert "mark_jobs_seen" not in src
    assert "unlimited" not in cfg.lower()


def test_timesjobs_backend_only():
    src = read("timesjobs_main.py")
    assert "connect_over_cdp" in src
    assert "webapp" not in src.lower()


def test_timesjobs_external_route_uses_shared_company_agent():
    src = read("timesjobs_agent.py")
    assert "CompanyWebsiteAgent" in src
    assert "external_submitted" in src
    assert "external_blocked" in src
    assert "external_error" in src


def test_timesjobs_apply_records_result_only_after_attempt():
    src = read("timesjobs_agent.py")
    pos_process = src.index("await self._process_job_page") if "await self._process_job_page" in src else -1
    pos_app = src.index("app(self.db, page.url")
    assert pos_process >= 0
    assert pos_app > pos_process


def test_timesjobs_search_results_use_button_pagination_not_url_arithmetic():
    src = read("timesjobs_agent.py")
    assert "button.pagination-next" in src
    assert "pagination-next" in src
    assert "_click_next_search_page" in src


def test_timesjobs_pagination_click_waits_for_new_result_urls():
    import asyncio
    import json
    import timesjobs_agent as module

    class FakeLocator:
        def __init__(self, page, kind):
            self.page = page
            self.kind = kind

        @property
        def first(self):
            return self

        async def count(self):
            return 1 if self.kind == "next" or self.kind == "jobs" else 0

        async def is_visible(self):
            return True

        async def is_disabled(self):
            return False

        async def scroll_into_view_if_needed(self, **_kwargs):
            return None

        async def click(self, **_kwargs):
            self.page.page_index = 2

        async def evaluate(self, _script):
            self.page.page_index = 2

        async def evaluate_all(self, _script):
            return self.page.result_urls[self.page.page_index]

    class FakePage:
        def __init__(self):
            self.url = "https://www.timesjobs.com/job-search?keywords=ai"
            self.page_index = 1
            self.result_urls = {
                1: ["https://www.timesjobs.com/job-detail/ai-1"],
                2: ["https://www.timesjobs.com/job-detail/ai-2"],
            }

        async def wait_for_timeout(self, *_args, **_kwargs):
            return None

        def locator(self, selector):
            if "job-detail" in selector:
                return FakeLocator(self, "jobs")
            if "pagination-next" in selector:
                return FakeLocator(self, "next")
            return FakeLocator(self, "other")

        def get_by_role(self, role, name=None):
            return FakeLocator(self, "next" if role == "button" and name is not None else "other")

    agent = module.TimesJobsAgent.__new__(module.TimesJobsAgent)
    agent.config = json.loads((ROOT / "role_config.json").read_text(encoding="utf-8"))
    moved = asyncio.run(agent._click_next_search_page(FakePage()))
    assert moved is True


def test_timesjobs_process_current_results_loops_through_next_pages():
    import asyncio
    import json
    import timesjobs_agent as module

    class FakePage:
        url = "https://www.timesjobs.com/job-search?keywords=ai"

    class FakeAgent(module.TimesJobsAgent):
        def __init__(self):
            self.config = json.loads((ROOT / "role_config.json").read_text(encoding="utf-8"))
            self.max_search_pages_per_role = 3
            self.target_applications = 10
            self.applied = 0
            self.processed = 0
            self.max_total_candidates = 1000
            self.page_calls = []
            self.next_calls = 0

        async def _process_current_results_page(self, context, page, page_number):
            self.page_calls.append(page_number)

        async def _click_next_search_page(self, page):
            self.next_calls += 1
            return self.next_calls < 2

    agent = FakeAgent()
    asyncio.run(agent._process_current_or_results(object(), FakePage()))
    assert agent.page_calls == [1, 2]
    assert agent.next_calls == 2


def test_timesjobs_job_tab_is_reused_across_candidate_loop():
    src = read("timesjobs_agent.py")
    start = src.index("async def _process_current_results_page")
    end = src.index("async def _search_page_fingerprint")
    block = src[start:end]
    assert "for url in urls:" in block
    assert "job_page = await context.new_page()" in block
    assert "if job_page.is_closed():" in block
    assert "await job_page.goto(url" in block
    assert "preserved_application_pages" in block
    assert "one dedicated TimesJobs job-detail tab" in block
    assert "job_page = await context.new_page()" in block  # only replacement after tab conversion
    # The candidate loop must not allocate a fresh tab unconditionally.
    loop_start = block.index("for url in urls:")
    loop_tail = block[loop_start:]
    # One allocation is the initial reusable tab, and one is the exceptional
    # replacement after that tab is converted into an application surface.
    assert loop_tail.count("job_page = await context.new_page()") == 2
