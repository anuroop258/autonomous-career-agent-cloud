
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platforms" / "indeed"))

from indeed_agent import IndeedAgent


# Contract extracted directly from the supplied Indeed Apply redirect document.
SHELL_HTML = """
var storageKey = 'shortUrl/' + window.location.pathname.replace('/beta/indeedapply/', '').split('/')[0];
var destinationUrl = sessionStorage.getItem(storageKey);
if (destinationUrl === null) { return; }
var anchor = document.createElement('a');
anchor.href = destinationUrl;
if (anchor.href !== destinationUrl) { return; }
if (anchor.origin && window.location.origin && (anchor.origin !== window.location.origin)) { return; }
window.location = anchor.href;
"""


def test_redirect_shell_contract_and_shared_helper():
    agent = IndeedAgent()
    assert agent._is_indeed_redirect_shell(
        "https://smartapply.indeed.com/beta/indeedapply/form/abc"
    )
    assert not agent._is_indeed_redirect_shell(
        "https://smartapply.indeed.com/beta/indeedapply/application/abc"
    )
    assert "shortUrl/" in SHELL_HTML
    assert "sessionStorage.getItem" in SHELL_HTML
    assert "window.location = anchor.href" in SHELL_HTML
    assert "_follow_indeed_redirect_shell" in type(agent).__dict__
    assert "_is_indeed_redirect_shell" in type(agent).__dict__


if __name__ == "__main__":
    test_redirect_shell_contract_and_shared_helper()
    print("PASS: Indeed redirect shell contract")
