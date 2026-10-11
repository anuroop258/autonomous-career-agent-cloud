from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
NEW_PORTALS = ("shine", "timesjobs", "glassdoor")


def test_merged_portals_are_registered_end_to_end():
    dispatcher = (ROOT / "main.py").read_text(encoding="utf-8")
    backend = (ROOT / "webapp/backend/main.py").read_text(encoding="utf-8")
    frontend = (ROOT / "webapp/frontend/src/pages/JobSearch.tsx").read_text(encoding="utf-8")
    browser = (ROOT / "webapp/frontend/src/pages/Browser.tsx").read_text(encoding="utf-8")
    jobs = (ROOT / "webapp/frontend/src/pages/Jobs.tsx").read_text(encoding="utf-8")
    logs = (ROOT / "webapp/frontend/src/pages/Logs.tsx").read_text(encoding="utf-8")
    for portal in NEW_PORTALS:
        assert f'"{portal}": {{' in dispatcher
        assert f'"{portal}"' in backend
        assert (ROOT / "platforms" / portal / f"{portal}_agent.py").exists() or (
            portal == "glassdoor" and (ROOT / "platforms/glassdoor/glassdoor_agent.py").exists()
        )
        assert f'"{portal}"' in frontend
        assert f'"{portal}"' in browser
        # The restored Jobs page renders its portal options from a PORTALS array,
        # so the option value is dynamic ({p}), not a literal JSX value attribute.
        portal_options = re.search(r"const PORTALS\s*=\s*\[(.*?)\]", jobs, re.S)
        assert portal_options and f'"{portal}"' in portal_options.group(1)
        assert f'"{portal}"' in logs


def test_unified_frontend_uses_isolated_ports_5175_and_8001():
    vite = (ROOT / "webapp/frontend/vite.config.ts").read_text(encoding="utf-8")
    env = (ROOT / "webapp/frontend/.env").read_text(encoding="utf-8")
    launcher = (ROOT / "desktop_launcher.pyw").read_text(encoding="utf-8")
    cmd = (ROOT / "webapp/START_WEBAPP.cmd").read_text(encoding="utf-8")
    docs = (ROOT / "webapp/README.md").read_text(encoding="utf-8")
    assert "port: 5175" in vite and "strictPort: true" in vite
    assert "VITE_API_BASE=http://127.0.0.1:8001" in env
    assert "BACKEND_PORT = 8001" in launcher
    assert "FRONTEND_PORT = 5175" in launcher
    assert "--port 8001" in cmd and "--port 5175" in cmd
    assert "localhost:5175" in docs
    assert "localhost:5173" not in docs
    assert "node free-port.mjs 5175" in (ROOT / "webapp/frontend/package.json").read_text(encoding="utf-8")
    assert "127.0.0.1:8001" in (ROOT / "webapp/frontend/src/api/client.ts").read_text(encoding="utf-8")
    assert "5175" in (ROOT / "webapp/FREE_WEBAPP_PORT.cmd").read_text(encoding="utf-8")
    assert "8001 = 'uvicorn" in launcher and "5175 = 'vite'" in launcher
    diagnostics = (ROOT / "webapp/CHECK_WEBAPP.cmd").read_text(encoding="utf-8")
    assert "LocalPort 5175" in diagnostics and "8001" in diagnostics


def test_new_portals_share_chrome_cdp_9222():
    backend = (ROOT / "webapp/backend/main.py").read_text(encoding="utf-8")
    dispatcher = (ROOT / "main.py").read_text(encoding="utf-8")
    for portal in NEW_PORTALS:
        assert re.search(rf'"{portal}"\s*:\s*\{{\s*"port": 9222', backend)
        assert re.search(rf'"{portal}"\s*:\s*\{{[^}}]*"port": 9222', dispatcher, re.S)


def test_shine_defaults_to_hyderabad_for_location_matching():
    cfg = (ROOT / "platforms" / "shine" / "role_config.json").read_text(encoding="utf-8")
    assert '"preferred_locations": ["Hyderabad"]' in cfg
