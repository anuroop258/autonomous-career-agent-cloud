from pathlib import Path
import json


def test_linkedin_native_apply_types_are_explicitly_configured():
    root = Path(__file__).resolve().parent
    cfg = json.loads((root / "linkedin_config.json").read_text(encoding="utf-8"))
    assert cfg["native_apply_types"] == ["easy_apply_single_step", "easy_apply_multi_step"]
    assert cfg["leave_native_apply_tab_open_on_unresolved"] is True


def test_unknown_question_explicitly_leaves_native_tab_open():
    root = Path(__file__).resolve().parent
    src = (root / "linkedin_agent.py").read_text(encoding="utf-8")
    assert 'await self._leave_native_tab_open(page, "unknown_question")' in src
    assert 'await self._leave_native_tab_open(page, "fill_failed")' in src
    assert 'keep_tab_open = True' in src


def test_native_type_classifier_exists():
    root = Path(__file__).resolve().parent
    src = (root / "linkedin_agent.py").read_text(encoding="utf-8")
    assert 'async def _detect_native_apply_type' in src
    assert 'easy_apply_single_step' in src
    assert 'easy_apply_multi_step' in src
