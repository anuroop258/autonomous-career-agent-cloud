# V40 Acceptance Ledger — TimesJobs Job-Tab Reuse

1. A TimesJobs results page may contain many job URLs; processing them must not create one persistent browser tab per job.
2. Reuse one dedicated job-detail tab for the candidate loop and close it when the page batch finishes.
3. Preserve the existing TimesJobs pagination, eligibility filtering, deduplication, apply routing, and external-company flow unchanged.
4. Regression checks must verify the source uses a reusable job tab and that the existing pagination tests still pass.
