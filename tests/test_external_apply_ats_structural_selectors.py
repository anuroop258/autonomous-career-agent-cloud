from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "application" / "common" / "company_website_agent.py"


def test_structural_apply_selectors_cover_oracle_workday_zoho():
    src = SRC.read_text(encoding="utf-8")
    assert '"button.apply-now-button"' in src
    assert '"[data-automation-id=adventureButton][role=button]"' in src
    assert '"a[data-automation-id=adventureButton][href*=\'/apply\']"' in src
    assert '"input[type=button][value=\'Apply Now\']"' in src
    assert '"input[type=button][id=\'zr-detail-view-applybtn\']"' in src


def test_oracle_apply_fixture_matches_structural_selector():
    html = '<button class="button apply-now-button"><span>Apply Now</span></button>'
    assert re.search(r'<button[^>]*class="[^"]*\bapply-now-button\b', html, re.I)


def test_workday_apply_fixture_matches_structural_selector():
    html = '<a href="/job/123/apply" role="button" data-automation-id="adventureButton">Apply</a>'
    assert 'data-automation-id="adventureButton"' in html
    assert 'role="button"' in html
    assert re.search(r'href="[^\"]*/apply', html, re.I)


def test_zoho_apply_fixture_matches_structural_selector():
    html = '<input type="button" value="Apply Now" class="tem1_applyBut" id="zr-detail-view-applybtn">'
    assert re.search(r'<input[^>]*type="button"[^>]*value="Apply Now"[^>]*id="zr-detail-view-applybtn"', html, re.I)
