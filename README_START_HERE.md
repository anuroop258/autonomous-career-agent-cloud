# Start here — free/no-card deployment

**Your next action:** download this kit, extract its contents into your existing project folder, and follow `FREE_DEPLOY_NO_CARD.md`. Do not redeploy on Render and do not push private profile/session files to GitHub.

This is an additive migration starter. It includes a Cloudflare Pages control page + D1 run-state API, a manually triggered GitHub Actions workflow that runs an existing portal agent on a temporary Linux runner, encrypted private data bundle tools, and session export/restore helpers.

It is **not** the full React analytics dashboard. The new control page only starts/stops runs and displays status/log tails. Existing job analytics, recruiters, approvals and resume UI endpoints are not migrated to Cloudflare yet. Test one Naukri run capped at one application before continuing.

Read the full instructions in `FREE_DEPLOY_NO_CARD.md` before committing or adding Cloudflare secrets.
