import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _matcher_class():
    path = ROOT / "platforms" / "indeed" / "jd_matcher.py"
    spec = importlib.util.spec_from_file_location("indeed_jd_matcher_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.JDMatcher


def test_indeed_full_jd_matching_includes_non_skill_terms():
    jd = "AI Engineer communication collaboration LLMs RAG Python cloud observability"
    result = _matcher_class()(str(ROOT / "platforms" / "indeed")).match("AI Engineer", jd)
    assert result["jd_exact_keyword_hits"]
    assert "jd_exact_keyword" in result["score_components"]
    assert "communication" in result["jd_soft_skill_missing"] or "communication" in result["jd_soft_skill_hits"]
