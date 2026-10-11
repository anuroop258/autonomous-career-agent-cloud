import inspect
import sys
for _m in ("storage", "qa_engine", "profile_reasoner", "jd_matcher"):
    sys.modules.pop(_m, None)
from pathlib import Path

PLATFORM=Path(__file__).resolve().parent
sys.path.insert(0,str(PLATFORM))

from platforms.glassdoor.glassdoor_agent import GlassdoorAgent  # noqa: E402


def test_native_control_and_external_skip_are_present():
    src=inspect.getsource(GlassdoorAgent.direct_apply_control)
    assert "easy\\s+apply" in src.lower()
    ext=inspect.getsource(GlassdoorAgent._click_skip_for_now)
    assert "skip\\s+for\\s+now" in ext.lower()


def test_external_route_uses_canonical_agent_after_destination_wait():
    src=inspect.getsource(GlassdoorAgent._run_external_company_flow)
    assert "wait_for_load_state" in src
    assert "60s maximum transition wait" in src
    assert "CompanyWebsiteAgent(" in src
    assert "filler.apply(" in src
    assert "external_apply_not_reached" in src


def test_glassdoor_domain_helpers():
    agent=GlassdoorAgent()
    assert agent._is_valid_job_url("https://www.glassdoor.co.in/job/ai-engineer-jobs-SRCH_KO0,11.htm")
    assert not agent._is_valid_job_url("https://in.indeed.com/viewjob?jk=12345678")


def test_search_url_shape():
    from platforms.glassdoor.glassdoor_main import build_search_url
    url=build_search_url("AI Engineer")
    assert "glassdoor.co.in/Job/jobs.htm" in url
    assert "sc.keyword=AI+Engineer" in url
    assert "locId=115" in url


def test_application_engine_facade():
    import importlib.util
    path = Path(__file__).resolve().parent / "application_engine.py"
    spec = importlib.util.spec_from_file_location("glassdoor_application_engine_v41", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.GlassdoorApplicationEngine.PLATFORM == "glassdoor"


def test_jobs_section_navigation_is_required_before_search():
    src = inspect.getsource(GlassdoorAgent.run_search)
    helper = inspect.getsource(GlassdoorAgent._open_jobs_section_first)
    assert "await self._open_jobs_section_first(page)" in src
    assert src.index("await self._open_jobs_section_first(page)") < src.index("current_url = search_url")
    assert 'f"{BASE}/Job/index.htm"' in helper
    assert 'name="Jobs", exact=True' in helper
    assert "refusing to bypass" in helper


def test_native_application_wait_helper_exists_and_checks_rendered_surface():
    src = inspect.getsource(GlassdoorAgent._wait_for_native_application_target)
    assert "context.pages" in src
    assert "pages_before" in src
    assert "application questions" in src
    assert "timeout_ms" in src


def test_control_label_probe_is_bounded_for_detaching_controls():
    src = inspect.getsource(GlassdoorAgent._control_label)
    assert "timeout=1500" in src

def test_external_apply_uses_dynamic_wait_and_employer_site_contract():
    src = inspect.getsource(GlassdoorAgent._wait_for_external_apply_control)
    assert "timeout_ms=10000" in src
    assert "_external_apply_control(page)" in src
    flow = inspect.getsource(GlassdoorAgent._run_external_company_flow)
    assert "await self._wait_for_external_apply_control" in flow
    assert "data-test='applyButton'" in inspect.getsource(GlassdoorAgent._external_apply_control)


def test_native_flow_delegates_to_indeed_reference_engine():
    src = inspect.getsource(GlassdoorAgent._run_native_indeed_flow)
    assert "IndeedAgent()" in src
    assert "_wait_for_native_application_target" in src
    assert "wait_for_application_ready" in src
    assert "detect_blocker" in src
    assert "run_application" in src


def test_external_flow_waits_for_canonical_company_page_before_form_engine():
    src = inspect.getsource(GlassdoorAgent._run_external_company_flow)
    assert "CompanyWebsiteAgent(" in src
    assert "await filler.wait_for_page(active)" in src
    assert "filler.apply(" in src


def test_native_and_external_paths_keep_application_surfaces_open_on_failure():
    src = inspect.getsource(GlassdoorAgent.process_job)
    assert "application_opened" in src
    assert "NATIVE APPLICATION PRESERVED" in src
    assert "external_apply_not_found" in src
    assert "external_apply_not_reached" in src
