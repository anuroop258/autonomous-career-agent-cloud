# V41 Acceptance Ledger — Three New Platforms Rewrite

## Requested outcome
- Remove Glassdoor, Shine, and TimesJobs from the web frontend run/Browser controls.
- Rebuild the three adapters around the proven Naukri/Indeed lifecycle:
  - deterministic search entry and pagination
  - result/card eligibility gate before opening
  - bounded job/application transition waits
  - explicit native vs external Apply classification
  - company-site flow delegated to the canonical form engine
  - native Glassdoor Easy Apply delegated to the proven Indeed SmartApply state machine
  - preserve application pages after Apply; close only temporary/rejected job tabs
  - never treat a click alone as a confirmed application
- Do not modify Naukri, Indeed, or LinkedIn runtime behavior.

## Reviewed gates
1. Python compileall over the package — required PASS.
2. Focused regression suite for Glassdoor/Shine/TimesJobs + frontend disconnect — required PASS.
3. Existing Indeed native wait/profile checks — required PASS.
4. Existing external-apply routing suite — report exact result and distinguish pre-existing LinkedIn static failure.
5. Re-extract final ZIP and rerun focused suite — required PASS.
6. Compare V40 → V41 changed-file scope — only requested frontend, three adapters, shared helper, tests/config/docs.
