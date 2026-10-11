from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / "naukri_agent.py").read_text(encoding="utf-8")
def test_naukri_agent_imports_path_for_external_tailoring():
    assert "from pathlib import Path" in TEXT
    assert "Path(__file__).with_name(\"profile.json\")" in TEXT
    assert "Path(str(tailored)).exists()" in TEXT
def test_external_apply_happens_after_tailored_resume_ready():
    start=TEXT.index("if await self._native_apply_target_is_external(page):")
    end=TEXT.index("async def ", start+10)
    branch=TEXT[start:end]
    assert branch.index("NAUKRI EXTERNAL RESUME READY") < branch.index("_click_external_apply_from_naukri(page)")
