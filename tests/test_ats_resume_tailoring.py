import re
import json
from pathlib import Path

import fitz

from resume_tailer import ATSAuthenticResumeTailor, compile_latex, extract_keyword_inventory, verify_pdf


ROOT = Path(__file__).resolve().parents[1]


def profile():
    return json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))


def test_literal_keyword_inventory_keeps_content_words_and_variants():
    inv = extract_keyword_inventory(
        "Build KPI reports and maintain KPIs in Python. Use Microsoft Excel and Excel. "
        "Documentation, Mathematics and Communication are required."
    )
    singles = {x.lower() for x in inv["single_word_keywords"]}
    assert "kpi" in singles
    assert "kpis" in singles
    assert "excel" in singles
    assert "python" in singles
    assert "documentation" in singles
    assert "mathematics" in singles
    assert "communication" in singles
    assert "second_pass_verified" in inv and inv["second_pass_verified"] is True


def test_phrase_inventory_rejects_obvious_duplicate_title_phrase():
    inv = extract_keyword_inventory("AI Engineer needs Python and RAG.", "AI Engineer")
    phrases = {p.lower() for p in inv["phrase_keywords"]}
    assert "ai engineer ai engineer" not in phrases


def test_tailoring_expands_supported_jd_wording_without_inventing():
    jd = (
        "AI Engineer with Python, retrieval augmented generation, LangChain, FAISS, "
        "FastAPI, SQL and AWS."
    )
    result = ATSAuthenticResumeTailor(
        profile(), ROOT / "resume" / "master_resume.tex"
    ).tailor(jd, "AI Engineer")

    assert "Retrieval Augmented Generation" in result.latex or "Retrieval-Augmented Generation" in result.latex
    assert any(x["keyword"].lower() == "retrieval augmented generation" for x in result.report["safe_additions"])
    assert "Airflow" not in result.latex
    assert result.report["second_pass_verified"] is True
    assert result.report["metrics_preserved"] is True
    assert result.report["stronger_bullet_selections"] == []
    assert all(n <= 25 for n in result.report["bullet_word_counts"])


def test_supported_project_keyword_is_rewritten_at_bullet_level():
    jd = "RAG engineer using retrieval augmented generation with FAISS."
    result = ATSAuthenticResumeTailor(
        profile(), ROOT / "resume" / "master_resume.tex"
    ).tailor(jd, "RAG Engineer")
    assert "Retrieval Augmented Generation" in result.latex or "Retrieval-Augmented Generation" in result.latex
    assert result.report["cv_check"]["exact_matches"] + result.report["cv_check"]["near_matches"] > 0


def test_education_certifications_are_immutable():
    master = (ROOT / "resume" / "master_resume.tex").read_text(encoding="utf-8")
    result = ATSAuthenticResumeTailor(
        profile(), ROOT / "resume" / "master_resume.tex"
    ).tailor("Python RAG FastAPI AWS", "AI Engineer")
    marker = r"\section{Education}"
    assert master[master.index(marker):] == result.latex[result.latex.index(marker):]


def test_unsupported_jd_keyword_is_not_added():
    jd = "Need Python and Airflow for production data pipelines."
    result = ATSAuthenticResumeTailor(
        profile(), ROOT / "resume" / "master_resume.tex"
    ).tailor(jd, "Data Engineer")
    assert "Airflow" not in result.latex
    assert any(x["keyword"].lower() == "airflow" for x in result.report["unsupported_keywords"])


def test_metrics_are_not_dropped_or_invented():
    result = ATSAuthenticResumeTailor(
        profile(), ROOT / "resume" / "master_resume.tex"
    ).tailor("AI Engineer Python RAG", "AI Engineer")
    assert result.report["metrics_preserved"] is True
    assert result.report["missing_metrics"] == []


def test_one_page_and_pdf_links(tmp_path):
    result = ATSAuthenticResumeTailor(
        profile(), ROOT / "resume" / "master_resume.tex"
    ).tailor("AI Engineer Python RAG FastAPI", "AI Engineer")
    pdf = compile_latex(result.latex, tmp_path, "resume")
    verification = verify_pdf(pdf)
    assert verification["page_count"] == 1
    assert verification["hyperlinks_checked"] is True
    assert verification["linkedin_url"] is True
    assert verification["github_url"] is True


def test_stronger_project_bullets_use_source_verified_metric_locks():
    jd = "AI support agent using Python, LLMs, RAG, classification and deterministic decision gates."
    result = ATSAuthenticResumeTailor(profile(), ROOT / "resume" / "master_resume.tex").tailor(jd, "AI Support Engineer")
    assert result.report["cv_check"]["total_keywords_checked"] > 0
    assert "83.3\\%" in result.latex
    assert "100\\%" in result.latex
    assert result.report["metrics_preserved"] is True
    assert result.report["prompt_spec"] == "RESUME_ATS_AUTHENTICITY_PROMPT.md"
    assert all(x["new_word_count"] <= 25 for x in result.report["stronger_bullet_selections"])


def test_metric_locks_preserve_master_project_numbers_after_tailoring():
    jd = "AI data quality engineer using Python, Pandas, SQL, anomaly detection and root cause analysis."
    result = ATSAuthenticResumeTailor(profile(), ROOT / "resume" / "master_resume.tex").tailor(jd, "Data Quality Engineer")
    master = (ROOT / "resume" / "master_resume.tex").read_text(encoding="utf-8")
    for metric in ["12,000", "800", "300", r"30\%", "1,000", "12"]:
        assert metric in master
        assert metric in result.latex


def test_cv_check_reports_exact_near_and_missing_keywords():
    jd = "Python SQL Kafka Airflow documentation mathematics KPIs."
    result = ATSAuthenticResumeTailor(profile(), ROOT / "resume" / "master_resume.tex").tailor(jd, "Data Engineer")
    check = result.report["cv_check"]
    assert check["total_keywords_checked"] >= 5
    assert check["exact_matches"] + check["near_matches"] + check["missing_matches"] == check["total_keywords_checked"]
    assert any(x["keyword"].lower() == "airflow" for x in result.report["unsupported_keywords"])


def test_professional_summary_is_tailored_from_verified_options_and_adds_supported_jd_keywords():
    jd = (
        "AI Engineer with Python, RAG, FastAPI, SQL and anomaly detection."
    )
    result = ATSAuthenticResumeTailor(
        profile(), ROOT / "resume" / "master_resume.tex"
    ).tailor(jd, "AI Engineer")
    a = result.latex.index(r"\section{Professional Summary}")
    b = result.latex.index(r"\section{Core Competencies / Skills}", a)
    summary = result.latex[a:b]
    assert result.report["summary_tailoring"]["master_outcome_preserved"] is True
    assert "83.3\\%" in summary
    assert "Technical focus includes" not in summary
    assert any(ch.isdigit() for ch in summary)


def test_title_metadata_is_excluded_from_tailoring_inventory():
    inv = extract_keyword_inventory(
        "Build Python tools and optimize NumPy and SQL workflows.",
        "Matlab Simulink Engineer - Tirupati - YOUNGMINDS TECHNOLOGY SOLUTIONS (YMTS) - 0 to 3 years of exper",
    )
    singles = {x.lower() for x in inv["single_word_keywords"]}
    assert {"python", "numpy", "sql"} <= singles
    assert "matlab" not in singles and "simulink" not in singles
    for junk in {"tirupati", "youngminds", "technology", "solutions", "ymts", "exper"}:
        assert junk not in singles
    assert inv["role_title"] == "Matlab Simulink Engineer"
    assert inv["excluded_title_metadata"]


def test_phrase_inventory_avoids_arbitrary_sliding_windows():
    inv = extract_keyword_inventory(
        "We build production-ready AI features using Prompt Engineering, RAG pipelines, vector search, and cross-functional collaboration.",
        "AI Engineer",
    )
    phrases = {p.lower() for p in inv["phrase_keywords"]}
    assert "python c++ c numpy" not in phrases
    assert "seeking highly skilled" not in phrases
    assert "prompt engineering" in phrases
    assert "vector search" in phrases
    assert "cross-functional collaboration" in phrases or "cross functional collaboration" in phrases


def test_summary_preserves_master_outcome_and_avoids_keyword_list_append():
    jd = "AI Engineer with RAG, LLM integration, agentic AI workflows and Python."
    result = ATSAuthenticResumeTailor(profile(), ROOT / "resume" / "master_resume.tex").tailor(jd, "AI Engineer")
    a = result.latex.index(r"\section{Professional Summary}")
    b = result.latex.index(r"\section{Core Competencies / Skills}", a)
    summary = result.latex[a:b]
    assert "83.3\\%" in summary
    assert "Technical focus includes" not in summary
    assert "0.35" not in summary
    assert result.report["summary_tailoring"]["master_outcome_preserved"] is True
    assert result.report["summary_tailoring"]["technical_focus_append_removed"] is True


def test_stronger_bank_bullets_cannot_replace_master_without_material_jd_gain():
    master = (ROOT / "resume" / "master_resume.tex").read_text(encoding="utf-8")
    jd = "AI Engineer role requiring Python, Playwright, FastAPI, Gemini API, LLMs and browser automation."
    result = ATSAuthenticResumeTailor(profile(), ROOT / "resume" / "master_resume.tex").tailor(jd, "AI Engineer")
    # Master bullets already express these capabilities; the older content-bank
    # 55+ variants should not replace them merely because they contain more metrics.
    assert result.latex.count("55+") == master.count("55+")
    assert result.report["stronger_bullet_selections"] == []
    assert any(x["change"] == "format_compaction_preserving_master_metrics" for x in result.report["rewritten_bullets"])


def test_missing_keywords_get_gap_classification_and_authenticity_risk():
    jd = "AI Engineer with Python, Airflow, Azure OpenAI, observability and CI/CD."
    result = ATSAuthenticResumeTailor(profile(), ROOT / "resume" / "master_resume.tex").tailor(jd, "AI Engineer")
    gaps = {x["keyword"].lower(): x["classification"] for x in result.report["gap_classifications"]}
    assert gaps.get("airflow") == "authenticity_risk"
    assert gaps.get("azure") == "authenticity_risk"
    assert result.report["authenticity_flags"]


def test_jd_delimiter_cleanup_and_camel_join_artifacts_are_normalized():
    inv = extract_keyword_inventory(
        "OverviewWe build RAG pipelinesIntegrate LLMs via APIs Azure OpenAI. "
        "Vector DBs andor MongoDBKnowledge, with PromptContext Engineering.",
        "AIML Engineer - Tirupati - YOUNGMINDs - 0 to 3 years exper",
    )
    singles = {x.lower() for x in inv["single_word_keywords"]}
    assert "pipelinesintegrate" not in singles
    assert "mongodbknowledge" not in singles
    assert "andor" not in singles
    assert "mongodb" in singles
    assert "context" in singles
    assert "azure" in singles
    assert "openai" in singles
    assert "retrieval-augmented generation" not in singles


def test_summary_uses_supported_literal_variant_without_dropping_master_outcome():
    jd = "AI Engineer requiring LLM integration and agentic AI workflows with Python."
    result = ATSAuthenticResumeTailor(profile(), ROOT / "resume" / "master_resume.tex").tailor(jd, "AI Engineer")
    a = result.latex.index(r"\section{Professional Summary}")
    b = result.latex.index(r"\section{Core Competencies / Skills}", a)
    summary = result.latex[a:b]
    assert "83.3\\%" in summary
    assert "LLM integration" in summary
    assert "agentic AI workflows" in summary
    assert "Technical focus includes" not in summary
    assert result.report["summary_tailoring"]["master_outcome_preserved"] is True


def test_supported_phrase_uses_exact_phrase_level_project_insertion():
    jd = "AI Engineer requiring LLM integration and RAG."
    result = ATSAuthenticResumeTailor(profile(), ROOT / "resume" / "master_resume.tex").tailor(jd, "AI Engineer")
    assert "Gemini LLM integration" in result.latex
    assert "native/external routing with LLM integration" not in result.latex


def test_phrase_components_are_not_counted_as_standalone_keywords():
    inv = extract_keyword_inventory(
        "Build Retrieval-Augmented Generation pipelines with Vector DBs and and/or MongoDB."
    )
    singles = {x.lower() for x in inv["single_word_keywords"]}
    assert "retrieval-augmented" not in singles
    assert "generation" not in singles
    assert "dbs" not in singles
    assert "and/or" not in singles


def test_real_operational_requirements_are_not_checker_glitches():
    jd = "AI Engineer with observability, monitoring, evaluation, deployment and integration."
    result = ATSAuthenticResumeTailor(profile(), ROOT / "resume" / "master_resume.tex").tailor(jd, "AI Engineer")
    gaps = {x["keyword"].lower(): x["classification"] for x in result.report["gap_classifications"]}
    for term in ["observability", "monitoring", "evaluation", "deployment", "integration"]:
        assert gaps.get(term) == "real_content_gap"


def test_supported_near_matches_are_not_reported_as_gaps():
    jd = "AI Engineer requiring LLM-based systems and vector search."
    result = ATSAuthenticResumeTailor(profile(), ROOT / "resume" / "master_resume.tex").tailor(jd, "AI Engineer")
    gaps = {x["keyword"].lower(): x["classification"] for x in result.report["gap_classifications"]}
    assert "llm-based" not in gaps
    assert "vector search" not in gaps


def test_skills_line_additions_are_cased_and_bounded():
    jd = "AIML Engineer requiring Vector DBs, Vector Search, LLM integration and transformer-based models."
    result = ATSAuthenticResumeTailor(profile(), ROOT / "resume" / "master_resume.tex").tailor(jd, "AIML Engineer")
    a = result.latex.index(r"\section{Core Competencies / Skills}")
    b = result.latex.index(r"\section{Projects/Experience}", a)
    section = result.latex[a:b]
    lines = [x for x in section.splitlines() if r"\textbf{" in x and ":}" in x]
    assert lines
    body = " ".join(lines)
    assert "vector dbs" not in body
    assert "llm integration" not in body
    assert "transformer-based models" not in body
    assert "Vector DBs" in body
    assert "LLM Integration" in body
    assert "Transformer-Based Models" in body
    # Check each competency body separately to enforce the 25-word constraint.
    for raw in section.splitlines():
        if r"\textbf{" in raw and ":}" in raw:
            payload = raw.split(":}", 1)[1]
            count = len(re.findall(r"\b[\w+#./&-]+\b", payload))
            assert count <= 25


def test_supported_terms_are_rewritten_at_bullet_level_instead_of_tacked_on():
    jd = "AIML Engineer requiring RAG pipelines, LLM integration and agentic AI workflows."
    result = ATSAuthenticResumeTailor(profile(), ROOT / "resume" / "master_resume.tex").tailor(jd, "AIML Engineer")
    assert "RAG" in result.latex
    assert "LLM integration" in result.latex
    assert "Developed an AI support agent with RAG pipelines for knowledge retrieval" in result.latex
    assert "Gemini LLM integration" in result.latex
    assert "native/external routing with LLM integration" not in result.latex
