# Shine fresher prefilter fix

Acceptance ledger:

- Non-eligible Shine result-card jobs must not be opened in a new tab.
- Fresher eligibility is accepted only for result-card ranges with a zero minimum and maximum <= 3 years (0-1, 0-2, 0-3, Freshers, 0 Yr).
- Non-eligible / deduped / rejected temporary job tabs must be closed.
- Eligible matching jobs remain open after JD matching / application handling.
- Existing Shine URL recognition and native Apply flow remain intact.
- Shine search caps remain 20 pages / 2000 candidates.

Evidence:

- Shine regression suite: 12 passed.
- Merged portal wiring + desktop launcher regression checks: 17 passed.
- Python compileall: passed.
- Source diff limited to Shine agent, Shine regression tests, Shine role config, and this report.

A live browser run was not performed in this environment because the Playwright browser executable was unavailable. The source/regression package checks therefore do not establish a live Shine-site run.
