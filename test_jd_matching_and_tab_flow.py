
import json
from pathlib import Path
import importlib.util

ROOT_JD_MATCHER = Path(__file__).resolve().parent / "jd_matcher.py"
spec = importlib.util.spec_from_file_location("root_jd_matcher_under_test", ROOT_JD_MATCHER)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
JDMatcher = module.JDMatcher

BASE = Path(__file__).resolve().parent
m = JDMatcher(BASE)

# Strong target-role JD should qualify even though only a subset of all profile
# skills appear. This guards against the old denominator bug.
strong = m.match(
    "Generative AI Engineer",
    """
    Build LLM and RAG applications using Python, LangChain, FAISS, Gemini,
    prompt engineering and vector databases. This is an entry-level role for
    fresh graduates with 0-1 years of experience.
    """,
)
assert strong["eligible"], strong
assert strong["score"] >= strong["threshold"], strong
assert strong["role_hits"], strong
assert strong["target_skill_hits"], strong

# Generic software/cloud wording must not qualify merely because it mentions
# many unrelated profile skills.
generic = m.match(
    "Backend Developer",
    """
    Build REST APIs using Java, C++, AWS, Git, SQL, Docker and Kubernetes.
    """,
)
assert not generic["eligible"], generic
assert not generic["ai_relevant"], generic

# Explicit mandatory experience must reject a fresher.
experienced = m.match(
    "AI Engineer",
    """
    Work on machine learning and generative AI systems. Must have at least
    2 years of relevant experience with LLMs and RAG.
    """,
)
assert not experienced["eligible"], experienced
assert not experienced["experience_ok"], experienced

# Native application processing must deliberately preserve the application tab.
agent_src = (BASE / "naukri_agent.py").read_text(encoding="utf-8")
anchor = 'leave_page_open = True'
assert anchor in agent_src
assert "Naukri-native application flow detected. Leaving this tab open after processing." in agent_src

print("JD MATCHING + NATIVE TAB PRESERVATION TESTS PASSED")


def test_external_company_site_apply_is_automated():
    # Contract test: a matching Naukri job whose Apply CTA leads to a company
    # site must click that validated CTA and hand the resulting page to the
    # canonical company-site filler.
    source = __import__("pathlib").Path("naukri_agent.py").read_text(encoding="utf-8")
    assert "_click_external_apply_from_naukri" in source
    assert "fill_external_with_company_agent" in source
    assert "MATCHED JOB HAS EXTERNAL/COMPANY-SITE APPLY CTA" in source
    assert "opening external application" in source
    assert "external_apply_skipped" not in source
