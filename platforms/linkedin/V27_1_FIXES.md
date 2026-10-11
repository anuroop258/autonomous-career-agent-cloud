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
