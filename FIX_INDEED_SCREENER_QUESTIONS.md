# Fix: Indeed screener questions not filled

Root cause: "Experience (in years)" had no matching answer rule, so the agent stopped with
"unknown question" on the first field and filled nothing.

Changed file: profile_reasoner.py (project root)
- "Experience (in years)" / "Total experience" -> candidate.total_experience_years
- "Comfortable with work timings / shift" -> preferences.night_shift
- "Expected Salary in numbers" -> full amount (400000) instead of LPA (4)

Not changed: "Is your portfolio attached?" has no stored answer (add via custom_qa_cli.py or set GEMINI_API_KEY).
