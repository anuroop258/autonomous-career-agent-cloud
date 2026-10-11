# Webapp Job Selection / Resume Tailoring Fix

## Problem fixed
The web dashboard used the SQLite `id` directly as the job identifier. Each portal has its own applications database, so `linkedin:15`, `indeed:15`, and `naukri:15` could collide when represented as simply `15`.

That could open the wrong job record, make the selected job appear without the correct metadata, and route Tailor Resume to the wrong row.

## New contract
Every job returned by `/api/jobs` has a stable cross-portal `job_ref`:

- `linkedin:<db_id>`
- `indeed:<db_id>`
- `naukri:<db_id>`

The frontend uses `job_ref` for job details and tailoring. Database `id` remains the application-row ID for application APIs.

## Metadata storage
LinkedIn and Indeed application records now persist company, description, match score, eligibility, and matched skills when a job is processed. Older rows without those columns are migrated automatically when the platform agent starts.

For older records, the web backend can recover company/role from recent real-agent run logs when available.

## UI behavior
- Jobs table: `Tailor Resume` works against the selected portal-specific job.
- Job title link: opens the correct portal-specific Job Details page.
- Job Details: always exposes `Tailor Resume` alongside `Open Job`.
- Resume Tailoring: selected jobs show company, role, portal, job reference, URL, and description before building.
- The tailoring endpoint refuses to silently create a resume using a URL as the role or `Unknown_Company` as the company.

## Easy Apply freeze
The frozen LinkedIn Easy Apply CTA layer was not changed by this webapp fix.
