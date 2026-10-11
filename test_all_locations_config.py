import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent

def test_indeed_has_no_location_filter():
    cfg = json.loads((ROOT / "platforms/indeed/role_config.json").read_text(encoding="utf-8"))
    assert cfg.get("preferred_locations", []) == []

def test_linkedin_has_no_location_filter():
    cfg = json.loads((ROOT / "platforms/linkedin/linkedin_config.json").read_text(encoding="utf-8"))
    assert cfg.get("locations", []) == []
