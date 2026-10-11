from pathlib import Path
import importlib.util
from importlib.machinery import SourceFileLoader


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "desktop_launcher.pyw"

loader = SourceFileLoader("desktop_launcher", str(MODULE_PATH))
spec = importlib.util.spec_from_loader("desktop_launcher", loader)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


def test_services_ready_requires_both_ports_and_http_health(monkeypatch):
    calls = []

    def fake_port(port):
        calls.append(("port", port))
        return True

    def fake_http(method, url, payload=None, timeout=8):
        calls.append(("http", method, url))
        assert url.endswith("/api/health")
        return {"ok": True}

    def fake_http_ready(url, timeout=2):
        calls.append(("frontend", url))
        return True

    monkeypatch.setattr(module, "port_open", fake_port)
    monkeypatch.setattr(module, "http_json", fake_http)
    monkeypatch.setattr(module, "http_ready", fake_http_ready)

    assert module.services_ready() is True
    assert ("port", module.BACKEND_PORT) in calls
    assert ("port", module.FRONTEND_PORT) in calls
    assert any(c[0] == "http" for c in calls)
    assert any(c[0] == "frontend" for c in calls)


def test_services_not_ready_when_frontend_http_is_unavailable(monkeypatch):
    monkeypatch.setattr(module, "port_open", lambda port: True)
    monkeypatch.setattr(module, "http_json", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(module, "http_ready", lambda *args, **kwargs: False)

    assert module.services_ready() is False
