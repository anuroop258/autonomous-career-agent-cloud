# Indeed Agent v11

Human-verification-safe build based on the working Naukri architecture.

Key behavior:
- Hyderabad-only location search.
- Preferred AI roles first.
- Accepts Fresher / 0-1 / 0-2 / 0-3 experience ranges and jobs with no explicit minimum requirement.
- Rejects jobs requiring more than 3 years and senior/non-entry-level titles.
- Deduplicates by Indeed `jk` job ID.
- Continues past individual navigation errors/timeouts.
- Detects Indeed/Cloudflare human-verification pages, pauses for manual completion, and resumes without bypassing the challenge.
- Never treats a `Just a moment...` / Cloudflare challenge page as a real JD.
