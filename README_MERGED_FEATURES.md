# Original ezyZip baseline + focused additions

The original Naukri/Indeed/LinkedIn engines remain authoritative. Added only:

- deterministic per-JD resume tailoring from `resume/master_resume.tex` (reorders existing skills/projects; does not invent or rewrite facts),
- tailored PDF handoff to Indeed/LinkedIn and Naukri external ATS; native Naukri keeps its account resume,
- persistent fuzzy-matched Custom Q&A,
- zero-dependency Custom Q&A browser UI,
- Gemini/Ollama disabled by default with at most one retry if explicitly enabled.

Run the original portal launchers:
`py main.py naukri`
`py main.py indeed`
`py main.py linkedin`

Custom Q&A:
`py career_agent_main.py qa add --question "..." --answer "..."`
`py career_agent_main.py qa list`
`py career_agent_main.py qa test --question "..." --options "Yes|No"`
`py career_agent_main.py qa remove --question "..."`

GUI: `py dashboard_app.py`
