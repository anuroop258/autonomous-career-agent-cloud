from pathlib import Path

ROOT = Path(__file__).resolve().parent


def test_linkedin_unknown_question_does_not_silently_skip():
    src = (ROOT / "platforms/linkedin/linkedin_agent.py").read_text(encoding="utf-8")
    unknown_block = src.split('UNKNOWN LINKEDIN QUESTION:', 1)[1].split('print(f"  Q: {q}\n  A: {answer}")', 1)[0]
    assert 'return "unknown_question"' in unknown_block
    assert "_leave_native_tab_open(page, \"unknown_question\")" in unknown_block


def test_indeed_unknown_question_does_not_abort_when_continue_works():
    src = (ROOT / "platforms/indeed/indeed_agent.py").read_text(encoding="utf-8")
    assert "if await self.click_continue(page):" in src
    assert 'return "unknown_question"' in src
