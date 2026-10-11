# V41 — Glassdoor / Shine / TimesJobs rebuild

This build temporarily removes Glassdoor, Shine, and TimesJobs from the web frontend's Run and Browser controls while their adapters are rebuilt.

## Flow contract

### Glassdoor
- Search and pagination stay on a dedicated search tab.
- Matching jobs use job-specific tailored resumes.
- External `Apply on employer site` uses the saved Glassdoor `data-test=applyButton` contract, waits for the employer/ATS destination, then delegates the form to the canonical company-site engine.
- Native `Easy Apply` delegates the post-click flow to the proven Indeed SmartApply wait + question/submit state machine.
- Application tabs remain open after Apply; temporary/rejected job tabs may close.

### Shine
- Search entry recovers from an existing result page via `Edit search`, then falls back to the dashboard.
- 0-year / entry-level card prefilter remains before opening job pages.
- Search follows real `Next` links through the configured 20-page / 2000-candidate limits.
- Native and external Apply routes use bounded transition/application-surface waits and the canonical company-site engine where a form is rendered.

### TimesJobs
- Search uses the observed skill/location/Let's Find flow.
- Result pages use the real `pagination-next` control and verify result URLs change.
- Per-job tabs follow the Naukri/Indeed lifecycle: create one temporary job tab, inspect it, and close it unless an application/application state needs to remain open.
- External and native Apply paths use bounded waits and the canonical company-site form engine.
- Search limits are normalized to 20 pages / 2000 candidates.

## Verification
- Focused new-platform regression suite: **42 passed**.
- Focused cross-platform compatibility suite (Indeed/native waits, external apply selectors, and the rebuilt three platforms): **54 passed**.
- Python `compileall`: passed before final packaging.
- Existing `tests/test_external_apply_routing.py`: contains one pre-existing stale LinkedIn static assertion; the same failure is present in V40 and is unrelated to this rebuild.
- Frontend source was updated, but `npm run build` could not be completed because the local Node dependency installation is incomplete (`vite/client` and `node` type definitions were unavailable in the environment).
