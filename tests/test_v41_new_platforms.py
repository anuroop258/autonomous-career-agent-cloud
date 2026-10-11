from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_frontend_exposes_all_connected_portals():
    for name in ("webapp/frontend/src/pages/JobSearch.tsx", "webapp/frontend/src/pages/Browser.tsx"):
        src = read(name)
        for portal in ("naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"):
            assert f'"{portal}"' in src or portal in src, (name, portal)


def test_timesjobs_limits_are_project_standard():
    cfg = json.loads((ROOT / "platforms/timesjobs/role_config.json").read_text(encoding="utf-8"))
    assert cfg["max_search_pages_per_role"] == 20
    assert cfg["max_total_candidates"] == 2000


def test_glassdoor_uses_indeed_native_state_machine():
    src = read("platforms/glassdoor/glassdoor_agent.py")
    assert "from platforms.indeed.indeed_agent import IndeedAgent" in src
    assert "_run_native_indeed_flow" in src
    assert "_wait_for_native_application_target" in src
    assert "wait_for_application_ready" in src
    assert "native.run_application" in src


def test_glassdoor_external_apply_matches_actual_saved_button():
    src = read("platforms/glassdoor/glassdoor_agent.py")
    assert 'button[data-test=\'applyButton\']:visible' in src
    assert "Apply on employer site" in src
    assert "external_apply_not_reached" in src
    assert "CompanyWebsiteAgent" in src


def test_shine_has_edit_search_recovery_and_pagination():
    src = read("platforms/shine/shine_agent.py")
    assert "Edit search" in src
    assert "_next_search_page_url" in src
    assert "SHINE NEXT PAGE" in src
    assert "max_search_pages_per_role" in src


def test_shine_has_external_and_native_apply_lifecycle():
    src = read("platforms/shine/shine_agent.py")
    assert "ApplicationFlow.find_apply" in src
    assert "wait_for_destination" in src
    assert "wait_for_application_surface" in src
    assert "external_apply_not_reached" in src
    assert "submission_unconfirmed" in src


def test_timesjobs_uses_bounded_external_and_native_waits():
    src = read("platforms/timesjobs/timesjobs_agent.py")
    assert "ApplicationFlow.find_apply" in src
    assert "wait_for_destination" in src
    assert "wait_for_application_surface" in src
    assert "external_apply_not_reached" in src
    assert "submission_unconfirmed" in src


def test_timesjobs_job_tabs_follow_v40_reusable_tab_contract():
    src = read("platforms/timesjobs/timesjobs_agent.py")
    block = src[src.index("async def _process_current_results_page"):src.index("async def _search_page_fingerprint")]
    assert "one dedicated TimesJobs job-detail tab" in block
    assert "for url in urls:" in block
    assert "if job_page.is_closed():" in block
    assert "await job_page.goto(url" in block
    assert "preserved_application_pages" in block
    # Exactly one initial reusable tab plus one exceptional replacement when
    # an application flow converts the job-detail tab into an application page.
    loop_tail = block[block.index("for url in urls:"):]
    assert loop_tail.count("job_page = await context.new_page()") == 2
    assert "if keep_open and not still_timesjobs" in block
    assert "await job_page.close()" in block


def test_shared_application_flow_has_bounded_destination_wait():
    src = read("platforms/common/application_flow.py")
    assert "timeout_ms: int = 60000" in src
    assert "about:blank" in src
    assert "source_domains" in src
