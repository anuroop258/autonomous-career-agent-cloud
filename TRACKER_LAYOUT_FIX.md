# Tracker UI readability update

Updated `webapp/frontend/src/pages/Tracker.tsx` and tracker-specific CSS in `webapp/frontend/src/index.css`.

- Replaced the cramped `repeat(n, minmax(200px, 1fr))` columns with fixed-width horizontal board lanes. Lanes scroll horizontally instead of squeezing all states into the viewport.
- Added summary counters for applications, needs-you, submitted/confirmed, and issues/skipped.
- Added status filters and a search field for role/company/portal/status/location.
- Gave each column a bounded, scrollable card area; improved card hierarchy, status pills, readable titles, and details links.
- Changed scraper placeholders `Unknown_Company` / `Unknown role` to human-readable `Company not detected` / `Role not detected` without mutating database data.
- Kept the backend application status values and details routes; no fake data added.

Validation: TSX transpilation/syntax and stylesheet brace balance checked. Full Vite build was not run because this ZIP intentionally excludes `node_modules`.
