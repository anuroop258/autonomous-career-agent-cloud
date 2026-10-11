# QA/Form Filling Fix

This patch targets the live Indeed SmartApply failure where `next_unanswered_field()` returned `None` and the code fell back to arbitrary page text such as "Ready to embark...".

Changes in `platforms/indeed/indeed_agent.py`:
- Form discovery now scans the main page and child frames.
- Deterministic fallback also scans child frames.
- Field groups retain `frame_index` metadata.
- Text filling scans all frames for editable controls.
- `run_application()` no longer calls `current_question()` when no real form field was discovered; it enters a safe `no_form_field` path instead of feeding page/banner text to the reasoner.

No changes were made to ProfileReasoner, JD matching, or the LLM provider hierarchy.

Validation on the supplied fixed project baseline:
- `python -m pytest -q` -> 33 passed.
