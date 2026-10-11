# Form Engine Hardening — 2026-09-22

This build keeps the existing 3-platform architecture and hardens the shared company-site application engine.

## Fixed

- Visible field labels now take precedence over incorrect HTML input types. A field labelled `Full name` will not be classified as email just because the ATS declares `type="email"`.
- Parent-container text is no longer used as a label when that container contains multiple controls. This prevents `Full name` and `Email address` from contaminating each other's classification.
- Added `aria-labelledby` and common Angular/Material label extraction.
- Honeypot fields such as `Leave this field empty` are detected and never filled.
- Open-ended fields such as `Experience and projects` are treated as questions, not numeric experience fields. Saved Custom Q&A can fill them; the engine does not write `0` into a textarea.
- Custom Q&A is restricted to open-ended/question fields and cannot overwrite deterministic identity/contact fields such as name, email, phone, location, resume, or terms.
- A required unknown field is considered resolved when the browser control is actually populated, so a valid saved Q&A answer is not rejected merely because the field has no deterministic profile semantic.
- After a verified external Apply click, the engine accepts real multi-step/SPA application handoffs even when the application stays on the same URL and the first step has only a few controls or a file input.
- Form readiness now records whether a full-form or minimal-handoff signal was used.
- Custom Q&A matching allows a distinctive token from short saved labels (for example `projects`) while still rejecting generic single-token matches such as `experience`.

## Existing behavior preserved

- LinkedIn native Easy Apply handling and unresolved-tab persistence.
- Indeed native resume upload flow.
- Naukri flow.
- Direct company-fill mode.
- Saved Q&A database (`applications.db`).
- Playwright auto-install on first run when the Python package is missing.
