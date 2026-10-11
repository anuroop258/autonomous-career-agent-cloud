import json
from pathlib import Path
from linkedin_agent import LinkedInAgent


def test_linkedin_files_and_config():
    root = Path(__file__).resolve().parent
    cfg = json.loads((root / "linkedin_config.json").read_text(encoding="utf-8"))
    assert cfg["target_native_applications"] == 20
    assert cfg["locations"] == []
    agent = LinkedInAgent()
    assert agent.target_applications == 20
    assert agent.max_candidates == 2000
