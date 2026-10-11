# Applications Resume Link Fix — v17

## Problem
The Applications table could show `Not generated` even for an eligible application whose tailored PDF existed because availability was matched only by the exact stored job URL. Runtime metadata can differ by tracking query/hash parameters, and older records may be identifiable by platform + job_key.

## Fix
- Normalize job URLs before resume metadata matching.
- Fall back to `platform + job_key` matching.
- Use the same robust lookup for `/api/applications` and `/api/jobs/{job_ref}/resume-file`.
- For eligible applications without a discoverable PDF, show `Generate Resume` instead of a dead `Not generated` label.
- After generation, the row refreshes and changes to `Resume PDF`, which opens the exact stored tailored PDF.
- Ineligible applications continue to show `Not generated` because the tailoring gate should not generate a resume for an ineligible job automatically.
