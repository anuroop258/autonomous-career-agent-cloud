# v27.1 minimal fixes

Based directly on the original v27 package. Existing profile.json, role_config.json,
JD matching, native QA flow, and application data are unchanged.

Fixes:
1. Native-only Apply preflight now rejects explicit company/employer/external Apply
   controls before clicking.
2. The actual Apply click has the same defense-in-depth external check.
3. Added a deterministic answer for the observed Naukri "programming ability" multiple
   choice when the exact strong-programming option is visible.

No external application form filler was enabled or expanded.

4. JD matching was corrected to score configured target-role skills rather than
   dividing matches by every profile skill. Role title relevance is weighted
   strongly, AI relevance remains a hard gate, and common skill aliases plus
   explicit experience ranges are recognized.
5. Native Naukri application tabs are now preserved after Apply/fill/submit. A
   newly opened Naukri application tab is detected and used when present; the
   original job-detail tab is closed only when that popup/tab takes over.
   Unknown/unverifiable native questions no longer cause the tab to be closed:
   the partially filled application remains open and processing continues to
   the next job.
