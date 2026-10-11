# Glassdoor Backend Agent — Phase 1

Backend-only Glassdoor agent; no frontend integration.

Native route:
Glassdoor job search -> full JD match -> Easy Apply -> Indeed SmartApply application flow (reuses the proven Indeed-native form engine).

External route:
Glassdoor Apply/Apply now -> click `Skip for now` on the Glassdoor preference modal observed in the supplied recording -> leave the external destination open; no external ATS filling/submission in this phase.

Persistent dedup uses the existing `applications.db` result history. Jobs are checked before processing and recorded through the normal result lifecycle.

Run:
`python platforms\glassdoor\glassdoor_main.py`
