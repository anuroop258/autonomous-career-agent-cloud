import asyncio
from jd_matcher import JDMatcher

def test_fresher_ai_software_developer_matches():
    jd = """
    Fresher-friendly role. 0 to 1 years relevant work experience.
    Basic programming knowledge in Python or JavaScript.
    Basic understanding of AI concepts like Machine Learning, Prompt Engineering,
    or RAG architecture. Exposure to LangChain, OpenAI APIs and Hugging Face.
    Interest in AI Agents, chatbots, or automation tools.
    """
    result = JDMatcher(".").match("Junior Software Developer", jd)
    assert result["eligible"] is True
    assert result["score"] >= 55
    assert "software developer" in result["software_role_hits"]
    assert "Python" in result["target_skill_hits"]
    assert "RAG" in result["target_skill_hits"]

def test_generic_software_developer_without_ai_does_not_match():
    jd = "Software developer. 0 to 1 years. Build web applications using Python and SQL."
    result = JDMatcher(".").match("Junior Software Developer", jd)
    assert result["eligible"] is False

def test_applied_filter_is_conservative():
    # Regression contract: only explicit Applied markers should filter a card.
    import re
    assert re.search(r"(?<![a-z])(?:applied|already applied|application submitted|you have applied)(?![a-z])",
                    "junior developer applied") is not None
    assert re.search(r"(?<![a-z])(?:applied|already applied|application submitted|you have applied)(?![a-z])",
                    "junior developer apply now") is None

def test_source_has_preopen_applied_filter_and_owned_tabs():
    src = open("naukri_agent.py", encoding="utf-8").read()
    assert "async def _filter_applied_search_urls" in src
    assert "Applied ignored before opening" in src
    assert "pages_before_apply = list(context.pages)" in src
    assert "leave_page_open = True" in src
