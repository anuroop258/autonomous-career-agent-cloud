# Company Extraction Fix

Company metadata is now captured and persisted for all three portals.

## LinkedIn
- Existing company selectors retained.
- Added data-testid/itemprop selectors.
- Added JobPosting JSON-LD `hiringOrganization.name` fallback.

## Indeed
- Existing deterministic selectors and JobPosting JSON-LD extraction remain.
- Dashboard metadata refresh now uses Indeed-specific selectors.

## Naukri
- Added explicit company selectors, itemprop selectors, and JobPosting JSON-LD extraction.
- Added deterministic title-pattern fallback for titles such as `Role - Location - Company - 0 to 2 years of experience`.
- Company, JD description, match score, eligibility, and matched skills are persisted to the Naukri applications database.
- Tailored resume generation receives the extracted company instead of defaulting to `Unknown_Company`.
- Dashboard fallback can recover company names for legacy Naukri rows when the stored title contains the company segment.

No application CTA / Easy Apply click logic was changed by this fix.
