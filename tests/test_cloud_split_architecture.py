from pathlib import Path
import os
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_render_blueprint_separates_api_worker_and_shared_database():
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    services = {service["name"]: service for service in blueprint["services"]}
    assert services["career-api"]["type"] == "web"
    assert services["career-worker"]["type"] == "worker"
    assert "disk" not in services["career-api"]
    assert services["career-worker"]["disk"]["mountPath"] == "/data"
    assert services["career-api"]["envVars"][-1]["fromDatabase"]["name"] == "career-agent-db"
    assert services["career-worker"]["envVars"][-1]["fromDatabase"]["name"] == "career-agent-db"
    assert any(group["name"] == "career-agent-secrets" for group in blueprint["envVarGroups"])


def test_cloud_worker_runs_existing_portal_entrypoint_and_cloud_mode_is_opt_in():
    worker = (ROOT / "cloud_worker.py").read_text(encoding="utf-8")
    backend = (ROOT / "webapp/backend/main.py").read_text(encoding="utf-8")
    assert '[sys.executable, str(ROOT / "main.py"), portal]' in worker
    assert 'CAREER_AGENT_EXECUTION_MODE' in backend
    assert 'if not CLOUD_SPLIT_MODE:' in backend
    assert 'enqueue_portal(portal)' in backend
    assert 'request_cancel_all()' in backend


def test_browser_session_encryption_key_is_shared_by_api_and_worker():
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    group = next(g for g in blueprint["envVarGroups"] if g["name"] == "career-agent-secrets")
    secrets = {v["key"]: v for v in group["envVars"]}
    assert secrets["CAREER_AGENT_API_KEY"]["generateValue"] is True
    assert secrets["CAREER_AGENT_SESSION_ENCRYPTION_KEY"]["generateValue"] is True
    assert all(any(item.get("fromGroup") == "career-agent-secrets" for item in service["envVars"])
               for service in blueprint["services"])


def test_snapshot_excludes_chrome_profiles_and_browser_session_directories():
    # Static guard: these high-sensitivity files must not be put in the DB snapshot.
    source = (ROOT / "cloud_queue.py").read_text(encoding="utf-8")
    assert '"browser_profiles"' not in source or "_shared_paths" in source
    shared_paths = source.split("def _shared_paths", 1)[1].split("def _make_bundle", 1)[0]
    assert "browser_sessions" not in shared_paths
    assert "browser_profiles" not in shared_paths


def test_snapshots_are_encrypted_before_storage_and_decrypted_on_restore():
    source = (ROOT / "cloud_queue.py").read_text(encoding="utf-8")
    assert "_session_cipher().encrypt(_make_bundle(include_files=include_files))" in source
    assert "_session_cipher().decrypt(encrypted_bundle)" in source
    assert "hashlib.sha256(encrypted_bundle).hexdigest()" in source
