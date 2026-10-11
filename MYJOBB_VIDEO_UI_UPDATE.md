# MyJobb video UI update

Applied to the actual V44 React frontend in `webapp/frontend`.

## Visual changes
- Reworked the shell to the recorded MyJobb layout: warm ivory header, beige sidebar, black active Jobs state, account/changelog/research/report items, and compact breadcrumb header.
- Reworked Applications to the recorded MyJobb structure: summary card, pill tabs, sort/search controls, five-column table, mint selected row, and receipt drawer.
- Added the receipt drawer interaction shown in the recording: blurred backdrop, right-side panel, application header, progress line, conversational copy, ticket/receipt card, timestamp rows, stamp and barcode.
- Reworked Job Details to the recorded MyJobb layout: JOB kicker, Save/Hide/Share controls, original-posting link, cream/blue hero, serif job title, match ring, match section, application activity and timeline.
- Reworked Jobs cards to match the recorded card treatment: mixed warm/blue header gradient, dark Apply button with gold accent, mixed metadata pills and serif-like scoring.

## Functional behavior
- All data still comes from the existing V44 FastAPI APIs.
- Application receipt data is fetched from `/api/applications/{id}`.
- Job detail data continues to use `/api/jobs/{job_ref}`.
- Resume tailoring, marking submitted, original posting and existing backend workflows remain wired.
