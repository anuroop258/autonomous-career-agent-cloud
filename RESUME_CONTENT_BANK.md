# Resume Content Bank

`resume_content_bank.json` is the source-verified option bank extracted from the uploaded resume variants:

- `ml_rg (1)(4).pdf` — applied ML, LLM agents, RAG, NLP, automation
- `ml_rg(2).pdf` — applied ML, LLM agents, RAG, computer vision, segmentation
- `Resume_(6).pdf` — applied ML, LLM agents, RAG, data analysis, statistical anomaly detection

## Stored options

- Professional-summary variants
- Skill-set variants
- Keyword groups
- Project variants with exact source bullets
- Project technology stacks and tags
- Metrics/evidence attached to each project
- Certification wording

## Tailoring behavior

- The master resume remains the immutable source used to build PDFs.
- The content bank is loaded by `resume_tailer.py` and ranked against the JD as advisory options.
- The ranked options are exposed in the tailoring report and the Resume Tailoring UI.
- The bank does not authorize unsupported claims or silently replace the master project set.
- Project/summary options are stored as data so future selection/reordering logic can consume them without re-parsing PDFs.
