from pathlib import Path


CURRENT = Path(__file__).resolve().parent / "indeed_agent.py"
SOURCE = CURRENT.read_text(encoding="utf-8")


def _method_block(name: str) -> str:
    marker = f"    async def {name}("
    start = SOURCE.index(marker)
    next_def = SOURCE.find("\n    async def ", start + len(marker))
    if next_def == -1:
        next_def = len(SOURCE)
    return SOURCE[start:next_def]


def test_next_unanswered_field_does_not_preempt_dom_order():
    from indeed_agent import IndeedAgent
    import asyncio

    class Stub(IndeedAgent):
        def __init__(self):
            pass

        async def form_field_groups(self, _page):
            return [
                {"kind": "text", "label": "Website", "options": []},
                {"kind": "single_select", "label": "Do you have experience?", "options": ["Yes", "No"]},
            ]

        async def _deterministic_form_field_fallback(self, _page):
            return {"kind": "text", "label": "LinkedIn Profile", "options": []}

    field = asyncio.run(Stub().next_unanswered_field(object()))
    assert field["label"] == "Website"


def test_native_question_loop_uses_label_and_options_from_discovered_field():
    assert 'q = next_field["label"] if next_field else await self.current_question(page)' in SOURCE
    assert 'next_field["options"] if next_field and next_field.get("options") else await self.visible_options(page)' in SOURCE
    assert 'deterministic_value = next_field.get("deterministic_value")' not in _method_block("run_application")


def test_native_verification_failure_is_diagnostic_not_terminal():
    block = _method_block("run_application")
    assert 'NOTE: could not re-confirm answer in the Indeed form (continuing anyway)' in block
    assert 'return "fill_verification_failed"' not in block


def test_click_continue_matches_reference_button_set():
    block = _method_block("click_continue")
    for name in ("Save", "Continue", "Next", "Review", "Done", "Apply again", "Apply Now", "Apply"):
        assert name in block
    assert "Submit your application" not in block
