# Naukri V2 regression-safe fixes

Preserved the existing deterministic Naukri flow, including attach-only CDP,
fresh job tabs, live Applied verification, native application handling, external
company-site skip, answer verification, and per-job timeout.

Added:
- pre-open search-card Applied filtering (conservative explicit markers only)
- pre-filtered Applied URLs are marked seen to avoid repeat processing
- separate diagnostics for exposed / unique / Applied ignored / new candidates
- secondary software/developer role signal when the JD is genuinely AI/ML relevant
- regression tests for the supplied Junior Software Developer JD and Applied filtering

Validation:
- all Python files compile successfully
- focused regression tests: 4 passed
