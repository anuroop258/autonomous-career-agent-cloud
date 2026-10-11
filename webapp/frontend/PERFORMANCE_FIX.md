# Performance fix

The UI previously polled several expensive REST endpoints every 3-8 seconds, including endpoints that scan all platform SQLite databases and resume metadata.

Changes:
- Single-flight/visibility-aware polling so requests cannot overlap.
- Dashboard now uses one aggregated `/api/dashboard` snapshot for top jobs, recent applications, and needs-attention data.
- Dashboard poll reduced to 20s; config 60s; automation 8s.
- Jobs/Applications/Tracker/Recruiters/Follow-ups/Approvals/QA polling slowed to practical intervals.
- Backend caches the combined application snapshot briefly and builds resume availability once per snapshot instead of scanning resume records for every row.
- `/api/applications` now supports `limit`/`offset`.
