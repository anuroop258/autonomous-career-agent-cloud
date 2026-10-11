from pathlib import Path

BACKEND = Path("webapp/backend/main.py")
FRONTEND = Path("webapp/frontend/src/pages/JobSearch.tsx")
CLIENT = Path("webapp/frontend/src/api/client.ts")

def test_backend_exposes_indeed_continue_endpoint():
    source = BACKEND.read_text(encoding="utf-8")
    assert "/api/automation/indeed/continue" in source
    assert "Indeed is not waiting for human verification." in source

def test_dashboard_has_explicit_indeed_continue_button():
    source = FRONTEND.read_text(encoding="utf-8")
    assert "Enter / Continue Indeed" in source
    assert "indeedHumanVerification" in source

def test_api_client_sends_explicit_continue_signal():
    source = CLIENT.read_text(encoding="utf-8")
    assert "continueIndeedHumanVerification" in source
    assert "/api/automation/indeed/continue" in source
