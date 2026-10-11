from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def test_main_accepts_company_fill_dispatch():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'sys.argv[1].lower() == "company-fill"' in text
    ast.parse(text)


def test_company_fill_exists_and_parses():
    text = (ROOT / "company_fill.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    assert any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in tree.body)


def test_custom_qa_hook_present_in_ai_form_engine():
    text = (ROOT / "src/application/common/ai_form_engine.py").read_text(encoding="utf-8")
    assert "from custom_qa_store import find_custom_answer" in text
    assert "custom_answer = find_custom_answer" in text
