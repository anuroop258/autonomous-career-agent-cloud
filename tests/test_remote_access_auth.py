"""Remote-access hardening: API key, CORS, lockout, UI serving."""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KEY = "k" * 32


def load_app(monkeypatch, key=None, origins=None):
    sys.path.insert(0, str(ROOT))
    for mod in [m for m in sys.modules if m == "webapp" or m.startswith("webapp.")]:
        sys.modules.pop(mod)
    if key is None:
        monkeypatch.delenv("CAREER_AGENT_API_KEY", raising=False)
    else:
        monkeypatch.setenv("CAREER_AGENT_API_KEY", key)
    if origins:
        monkeypatch.setenv("CAREER_AGENT_ALLOWED_ORIGINS", origins)
    else:
        monkeypatch.delenv("CAREER_AGENT_ALLOWED_ORIGINS", raising=False)
    module = importlib.import_module("webapp.backend.main")
    from fastapi.testclient import TestClient
    return module, TestClient(module.app)


def test_without_key_everything_is_open_like_before(monkeypatch):
    _, c = load_app(monkeypatch)
    assert c.get("/api/auth/status").json() == {"auth_required": False, "cloud": False}
    assert c.get("/api/dashboard").status_code == 200
    assert c.get("/docs").status_code == 200


def test_with_key_requests_are_rejected_without_it(monkeypatch):
    _, c = load_app(monkeypatch, KEY)
    assert c.get("/api/auth/status").json() == {"auth_required": True, "cloud": False}
    for path in ("/api/dashboard", "/api/jobs", "/api/applications", "/api/qa", "/api/logs/raw", "/api/config"):
        assert c.get(path).status_code == 401, path
    assert c.post("/api/automation/start", json={"portals": ["indeed"]}).status_code == 401
    assert c.post("/api/automation/stop").status_code == 401


def test_valid_key_header_and_bearer_work(monkeypatch):
    _, c = load_app(monkeypatch, KEY)
    assert c.get("/api/dashboard", headers={"X-API-Key": KEY}).status_code == 200
    assert c.get("/api/dashboard", headers={"Authorization": f"Bearer {KEY}"}).status_code == 200
    assert c.get("/api/auth/check", headers={"X-API-Key": KEY}).json() == {"ok": True}
    assert c.get("/api/dashboard", headers={"X-API-Key": KEY + "x"}).status_code == 401


def test_key_in_url_only_allowed_for_resume_download(monkeypatch):
    _, c = load_app(monkeypatch, KEY)
    assert c.get(f"/api/dashboard?api_key={KEY}").status_code == 401
    assert c.get(f"/api/jobs?api_key={KEY}").status_code == 401
    r = c.get(f"/api/jobs/nope/resume-file?api_key={KEY}")
    assert r.status_code != 401          # authenticated (then 404: no such job)
    assert c.get("/api/jobs/nope/resume-file").status_code == 401


def test_health_is_open_but_leaks_no_paths_when_locked(monkeypatch):
    _, c = load_app(monkeypatch, KEY)
    assert c.get("/api/health").json() == {"ok": True}


def test_api_schema_hidden_when_locked(monkeypatch):
    _, c = load_app(monkeypatch, KEY)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code in (401, 404), path
        assert "paths" not in c.get(path).text


def test_lockout_after_repeated_wrong_keys(monkeypatch):
    _, c = load_app(monkeypatch, KEY)
    for _ in range(10):
        assert c.get("/api/dashboard", headers={"X-API-Key": "wrong-wrong-wrong"}).status_code == 401
    assert c.get("/api/dashboard", headers={"X-API-Key": "wrong-wrong-wrong"}).status_code == 429
    # even the right key is refused while locked out from that client
    assert c.get("/api/dashboard", headers={"X-API-Key": KEY}).status_code == 429


def test_missing_key_does_not_count_toward_lockout(monkeypatch):
    _, c = load_app(monkeypatch, KEY)
    for _ in range(25):
        assert c.get("/api/dashboard").status_code == 401
    assert c.get("/api/dashboard", headers={"X-API-Key": KEY}).status_code == 200


def test_short_key_is_refused_at_startup(monkeypatch):
    with pytest.raises(RuntimeError):
        load_app(monkeypatch, "short")


def test_cors_is_not_wildcard_and_preflight_passes_auth(monkeypatch):
    _, c = load_app(monkeypatch, KEY, origins="https://agent.example.com")
    ok = c.options("/api/dashboard", headers={
        "Origin": "https://agent.example.com", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "x-api-key"})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "https://agent.example.com"
    bad = c.options("/api/dashboard", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers
    # a 401 still carries CORS headers so the browser can show a proper error
    r = c.get("/api/dashboard", headers={"Origin": "https://agent.example.com"})
    assert r.status_code == 401
    assert r.headers.get("access-control-allow-origin") == "https://agent.example.com"


def test_ui_is_served_and_api_still_wins(monkeypatch, tmp_path):
    dist = ROOT / "webapp" / "frontend" / "dist"
    created = not dist.exists()
    dist.mkdir(parents=True, exist_ok=True)
    index = dist / "index.html"
    had_index = index.exists()
    if not had_index:
        index.write_text("<html>ui</html>")
    try:
        _, c = load_app(monkeypatch, KEY)
        assert c.get("/").status_code == 200                       # shell is public
        assert c.get("/api/dashboard").status_code == 401          # data is not
        assert c.get("/api/auth/status").status_code == 200
        assert c.get("/applications.db").status_code == 404        # nothing outside dist
        assert c.get("/profile.json").status_code == 404
        assert c.get("/..%2fprofile.json").status_code in (400, 404)
    finally:
        if not had_index:
            index.unlink()
        if created:
            dist.rmdir()


def test_cloud_mode_allows_managed_browser_routes(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_AGENT_CLOUD", "1")
    monkeypatch.setenv("CAREER_AGENT_CLOUD_BROWSER", "1")
    module, c = load_app(monkeypatch, KEY)
    h = {"X-API-Key": KEY}
    assert c.get("/api/auth/status").json() == {"auth_required": True, "cloud": True}
    # Keep the test hermetic: no real Chromium or agent subprocess is launched.
    monkeypatch.setattr(module, "_chrome_executable", lambda: "/bin/true")
    monkeypatch.setattr(module, "_port_open", lambda port: True)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: object())
    launched = c.post("/api/portal/launch", json={"portal": "indeed"}, headers=h)
    assert launched.status_code == 200, launched.text
    assert launched.json()["cloud_browser"] is True
    monkeypatch.setattr(module, "_refresh_run_state", lambda: None)
    monkeypatch.setattr(module, "_start_one", lambda portal: {"portal": portal, "pid": 123, "already_running": False})
    started = c.post("/api/automation/start", json={"portals": ["indeed"]}, headers=h)
    assert started.status_code == 200, started.text
    assert c.get("/api/dashboard", headers=h).status_code == 200


def test_cloud_session_import_requires_key_and_persists_session(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_AGENT_CLOUD", "1")
    module, c = load_app(monkeypatch, KEY)
    module.BROWSER_SESSION_DIR = tmp_path / "sessions"
    body = {"portal": "indeed", "storage_state": {"cookies": [{"name": "sid", "value": "example", "domain": ".indeed.com", "path": "/"}], "origins": []}}
    assert c.post("/api/browser/session/import", json=body).status_code == 401
    response = c.post("/api/browser/session/import", json=body, headers={"X-API-Key": KEY})
    assert response.status_code == 200, response.text
    saved = module.BROWSER_SESSION_DIR / "indeed.json"
    assert saved.exists()
    assert '"sid"' in saved.read_text(encoding="utf-8")
