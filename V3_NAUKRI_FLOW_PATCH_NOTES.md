# V3 Naukri Flow Patch

This build is based directly on the V3 lineage. It does not import the later V10-V12 architecture refactor.

Changes are limited to Naukri runtime flow safety:

- Fixed fixed-delay Playwright `wait_for_timeout()` calls in `naukri_agent.py` by using `asyncio.sleep()` for non-blocking waits. Browser actions and timing values are otherwise unchanged.
- Strengthened pre-open Applied filtering by finding the smallest result-card ancestor containing exactly one wanted job link and inspecting rendered text plus aria/title/status attributes.
- Kept the existing live Applied check as defense-in-depth, but changed it to bounded batched DOM reads.
- Added an explicit Naukri "application incomplete / mandatory information missing" stop-point. The current application tab remains open and no further controls are clicked.
- Preserved V3 rules: one fresh tab per job, native application tabs remain open, unknown/unverified questions stop safely with the tab open, matching external/company-site Apply CTAs are never clicked, and the next job continues in a fresh tab.

No LinkedIn or Indeed browser-flow code was changed.
