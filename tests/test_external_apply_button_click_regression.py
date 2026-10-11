from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "application" / "common" / "company_website_agent.py"


def _click_apply_source():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "click_apply":
            return node, SRC.read_text(encoding="utf-8")
    raise AssertionError("click_apply not found")


def test_external_fast_path_recognizes_plain_apply_and_apply_now():
    node, src = _click_apply_source()
    block = src[src.index("fast_patterns =", src.index("async def click_apply")):src.index("for frame in [page]", src.index("fast_patterns ="))]
    assert 're.compile(r"^\\s*apply\\s*$", re.I)' in block
    assert 're.compile(r"^\\s*apply\\s+now\\s*$", re.I)' in block


def test_external_fast_path_click_failure_continues_to_other_candidates():
    node, src = _click_apply_source()
    click_error = 'await self.record("apply_button_click_error", error=str(exc))'
    start = src.index(click_error)
    tail = src[start:start + 500]
    assert "continue" in tail
    assert "return False" not in tail
