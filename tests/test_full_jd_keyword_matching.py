
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("root_jd_matcher_full_jd", ROOT / "jd_matcher.py")
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MODULE)
JDMatcher = _MODULE.JDMatcher

JD = """
Role Overview We are seeking a highly skilled AIML Engineer to design, develop,
and deploy advanced AI solutions leveraging LLMs, RAG architectures, and agentic AI systems.
The ideal candidate will have deep Python expertise, strong NLP knowledge, and hands-on
experience integrating AI models into scalable, production-grade cloud environments.
Key Responsibilities include collaboration with cross-functional teams and strong communication.
Required Qualifications include expert-level proficiency in Python, strong experience with LLM integration,
RAG architectures, prompt/context engineering, transformer-based models, vector databases, CI/CD,
cloud deployment, observability, monitoring, and evaluation frameworks.
"""


def test_full_jd_keyword_matching_includes_non_skill_soft_skill_language():
    result = JDMatcher(str(ROOT)).match("AI/ML Engineer", JD)
    hits = {x.lower() for x in result["jd_exact_keyword_hits"]}
    missing = {x.lower() for x in result["jd_missing_keyword_hits"]}
    assert "communication" in missing or "collaboration" in missing or "cross-functional" in missing
    assert any(x in hits for x in {"production-grade", "cloud", "llms", "rag", "python", "nlp"})
    assert "llms" in hits
    assert "rag" in hits
    assert result["jd_exact_keyword_coverage"] > 0
    assert "jd_exact_keyword" in result["score_components"]


def test_full_jd_match_does_not_treat_unsupported_terms_as_supported_evidence():
    result = JDMatcher(str(ROOT)).match("AI/ML Engineer", "Python RAG Airflow Kubernetes CI/CD observability")
    missing = {x.lower() for x in result["jd_missing_keyword_hits"]}
    assert "airflow" in missing or "kubernetes" in missing


def test_soft_skill_match_is_bounded_and_cannot_bypass_role_experience_gate():
    result = JDMatcher(str(ROOT)).match("Senior Manager", "communication collaboration leadership teamwork Python")
    assert result["eligible"] is False
    assert result["seniority_block"] is not None
