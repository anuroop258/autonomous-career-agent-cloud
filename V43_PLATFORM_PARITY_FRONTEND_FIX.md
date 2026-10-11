# V43 Platform Parity + Frontend Fix

## Changes

- Connected Shine, TimesJobs, and Glassdoor to the unified frontend Job Search, Browser, Jobs, and Logs surfaces.
- Shine now uses Hyderabad as its configured preferred location.
- TimesJobs now reuses a dedicated job-detail tab across the candidate loop and creates a replacement only when an application flow converts that tab into an application surface.
- LinkedIn external employer-site Apply now restores the controlled V38 flow: validate and click the external CTA, preserve the source job tab, then hand the resulting company-site page to CompanyWebsiteAgent.
- Indeed form option routing now uses the options attached to the selected field and only falls back to page-wide options when no field was selected.
- Existing full-JD exact/missing keyword evidence and the GenAI relevance gate remain protected by regression tests.

## Verification

The scoped Python/frontend-static regression suite was rerun after these changes. Frontend production bundling could not be completed in the extracted environment because npm dependency installation timed out and the local `node_modules` tree remained incomplete; no build-pass claim is made for that gate.
