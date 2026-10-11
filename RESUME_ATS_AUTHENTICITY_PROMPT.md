# Resume ATS + Authenticity Optimization — Full Prompt

I'll give you the full job description text (I'll unlock/screenshot every locked keyword first if it's an image), plus my current resume.

## Phase 0 — Authenticity / Reality Check (run this BEFORE keyword work)

Before touching keywords, read my resume the way a skeptical recruiter would and flag anything that sounds copy-pasted from a job description rather than describing something I actually did — especially if I'm a student/fresher with no formal work experience.

- Don't just flag — rewrite each flagged bullet/summary line into something a student project could actually support.

## Phase 1 — Keyword Extraction

Extract every keyword literally — not just tools and tech (SQL, Python, Airflow), but every single-word adjective, soft skill, and domain noun too, including generic-sounding ones (Documentation, Mathematics, KPIs). Don't group or summarize — list them all individually. Log singular and plural separately (KPI / KPIs), and bare vs. branded names separately (Excel / Advanced Excel / Microsoft Excel, Power BI / Microsoft Power BI).

Do a second pass: re-read the raw JD word-by-word against your own list and add anything missed the first time. Don't show me the table until this second pass is done.

## Phase 2 — Match Check

Check each keyword one by one against my resume as an exact/near-exact string, not a paraphrase (ATS checkers do literal matching). Show me a table: **keyword → in resume (yes/no) → exact wording used**.

## Phase 3 — Rebuild the Resume

Add all applicable keywords into my resume, but never at the expense of authenticity from Phase 0. Follow these rules:

**Structure & formatting**
- Keep it one page.
- Every bullet starts with a capital letter and ends with the same punctuation style — pick one and apply it consistently throughout (either periods on all bullets or none).
- Keep every bullet and competency line under ~25 words. No long run-on bullets.
- Use a clean single-column layout (no tables/text boxes/graphics) so parsing doesn't break.

**Write projects as engineering stories, not keyword lists**
- Structure each project as problem → implementation → outcome, not a bag of buzzwords.
- Name the actual architecture/technique: e.g. for a RAG chatbot, call out the specific pieces used — embeddings, chunking strategy, vector index (FAISS/etc.), retrieval pipeline, hallucination handling — instead of just listing "LangChain, AI, chatbot."
- Prefer bullets that show what was built and how it worked over bullets that describe generic responsibilities.
- Where the summary currently leans on keyword-heavy claims, replace it with a version grounded in the actual projects — the summary should be provable by the bullets beneath it, not a superset of them.

**Content quality**
- Quantify aggressively: every bullet should include a hard number, %, count, or timeframe wherever honestly possible. Flag any bullet that can't be truthfully quantified instead of inventing a number (e.g., turn "Ran SQL/Python cohort analysis calculating retention rate, repeat purchase rate, and CLV" into a version with dataset size, time period, or a measurable outcome).
- Add at least one quantified detail into the Professional Summary itself, not just project bullets.
- No verb (e.g., "Built") should appear more than 2 times across the resume. Flag every verb that repeats 3+ times and swap in distinct, accurate alternatives (Developed, Engineered, Constructed, Assembled, Automated, etc.) matched to what was actually done.
- Avoid repeating "analysis" / "data" back-to-back — vary with accurate synonyms (evaluated, examined, modeled, interpreted, optimized, visualized) where it reflects what was actually done.
- Avoid vague filler/buzzwords used alone with no concrete backing ("enable," "organized," "collaborative") — replace with specific, evidence-backed phrasing. Don't flag genuinely technical terms (e.g., "validated") as buzzwords just because they sound soft.
- If honestly applicable, work in data modeling, statistical analysis, data validation, KPI reporting, report automation, and data storytelling — only where they reflect something I actually did. Flag as a gap instead of fabricating if not.
- Tighten dense corporate-speak bullets so they read as real and specific, not inflated.
- Don't pad word count for its own sake — a one-page resume is fine as long as it's substantive; only expand a bullet if there's a genuine concrete result to add.

**Fixes**
- Fix Job Title Match and Education Match by adjusting wording where honestly accurate — but never by implying a title/role/seniority I haven't held.
- Use full plain-text URLs for LinkedIn/GitHub (e.g., linkedin.com/in/you) instead of relying on hidden hyperlinks, since ATS parses plain text more reliably — but also keep them as real clickable hyperlinks in the file itself.
- Tell me plainly, for each flagged issue, whether it looks like a checker glitch, a real content gap, or an authenticity risk (Phase 0 style).

## Phase 4 — Output & Verification

- Give me both .docx and .pdf.
- Verify hyperlinks are real and clickable programmatically in the actual output file (e.g., via pdfplumber annotations), not just visually — before sending.
- Re-check page count and rendering after every edit.
- Overall goal: optimize for ATS, recruiters, *and* interview credibility — prove impact with specifics, not keyword stuffing or borrowed job-description language. Replace generic skill lists and corporate-sounding claims with quantified, problem-focused achievements that read as things I actually did (e.g., "SQL on 10k+ rows," "5-page Power BI dashboard," specific outcomes).
