# CareerAgent Cloudflare API + counter repair

This patch is additive to the full CareerAgent project and keeps the existing React dashboard. It adds the Cloudflare Pages Functions that serve the dashboard APIs, the D1 migrations, and the local data-publisher tool used to populate the public dashboard.

## Why the dashboard can show HTML instead of JSON

The frontend calls same-origin endpoints such as `/api/dashboard`, `/api/jobs`, `/api/preferences`, and `/api/search/jobs`. If a Pages Functions handler is missing or the Pages project is configured with the wrong project root, Pages can serve the single-page app's `index.html` for an API request. The frontend then tries to parse `<!doctype html>` as JSON and fails. The new `functions/_middleware.js` returns a JSON 404 for missing/non-JSON `/api/*` handlers, and the previously missing Cloudflare handlers for `/api/preferences` and `/api/search/jobs` are included.

## Cloudflare Pages build configuration

Keep the Pages **root directory empty** (repository root) so Cloudflare discovers the root-level `functions/` directory. Configure:

- Build command: `cd webapp/frontend && npm ci && npm run build`
- Build output directory: `webapp/frontend/dist`
- Production D1 binding: variable name `DB`, database `career-agent-control`

Do not set the root directory to `webapp/frontend`; that would put the Functions folder outside the Pages project's root.

## Apply the D1 schema

In Cloudflare Dashboard → Workers & Pages → D1 → `career-agent-control` → Console, run these files in order, from the repository root:

1. `migrations/0001_control.sql`
2. `migrations/0002_dashboard_data.sql`

Both use `IF NOT EXISTS` and are designed to be safe to reapply. The first creates the existing cloud task table if it is not already present; the second adds `jobs`, `applications`, preferences/config storage, logs, resume metadata/files, recruiters, outreach, approvals, and task details.

Confirm the Pages project's D1 binding is named exactly `DB` for Production (and Preview if needed).

## Required Cloudflare settings

Configure these in Pages → Settings → Variables and Secrets. Never put secrets in frontend code or commit them to Git:

- `AUTOMATION_PASSWORD` (**secret**) — choose the password used for automation actions.
- `DASHBOARD_API_KEY` (**secret**) — integration key for trusted runner callbacks and local data publishing.
- `GH_DISPATCH_TOKEN` (**secret**) — fine-grained token with Actions: read/write on the source repository.
- `GH_REPO_OWNER` = `anuroop258`
- `GH_REPO_NAME` = `autonomous-career-agent-cloud`
- `GH_WORKFLOW_FILE` = `free-cloud-run.yml`

In the GitHub source repository → Settings → Secrets and variables → Actions, configure:

- Secrets: `CAREER_AGENT_DATA_TOKEN` (fine-grained token with read/write access to the private data repo), `CAREER_AGENT_PRIVATE_BUNDLE_KEY` (Fernet key for the encrypted data bundle), and `CLOUD_CONTROL_API_KEY` (must match Cloudflare `DASHBOARD_API_KEY`).
- Variables: `CAREER_AGENT_DATA_REPO` = `anuroop258/autonomous-career-agent-private-data`, and `CLOUD_CONTROL_API_BASE` = `https://autonomous-career-agent-cloud.pages.dev`.

Do not paste secret values into chat.

Read APIs are public. `/api/data/sync` and `/api/worker/*` require `X-API-Key`; start/stop/continue, browser-launch, and resume-tailoring actions require `X-Automation-Password`. The UI prompts for the password before dispatching a resume-tailoring cloud task. Cloud mode still does not support a permanent local CDP browser; start a cloud run from Job Search to run Playwright on the temporary GitHub runner.

## Populate / refresh dashboard counters

The D1 tables start empty until a sync has run. `jobs_discovered`, `eligible`, `applications_total`, and `applications_submitted` are computed from D1 rows; they are not live reads of the SQLite files on your Windows computer. The tool `tools/publish_dashboard_data.py` exports dashboard records from the project's local SQLite databases and sends them in small batches to `/api/data/sync`. Before publishing it replaces the prior mirrored snapshot so stale rows from old exports cannot keep inflating the counters. It deliberately does not upload browser cookies or session state.

From PowerShell at the project root:

```powershell
py tools\publish_dashboard_data.py
```

By default it looks for the existing local file `cloud_private/dashboard_api_key.txt` and publishes to `https://autonomous-career-agent-cloud.pages.dev`. If you keep the integration key in an environment variable instead, set `CLOUD_CONTROL_API_KEY` in that terminal and run:

```powershell
py tools\publish_dashboard_data.py --key-env
```

Do not create or paste this key into the React frontend. If publishing returns 404/non-JSON, the Functions directory has not been deployed from the repository root yet. If it returns `D1 binding DB is missing`, configure the D1 binding. If it reports missing tables, apply the migrations first.

From the updated local archive, the publisher's read-only inventory check finds **702 job rows**, **101 recognized application-workflow rows**, **101 eligible rows**, and **7 submitted/applied rows**. If D1 is replaced with this snapshot and no new runs have changed the local data, those are the expected `jobs_discovered`, `applications_total`, `eligible`, and `applications_submitted` counters. This calculation was done locally; the live Cloudflare database has not been read from this environment.

After a successful sync, verify the deployed JSON endpoints from PowerShell:

```powershell
Invoke-RestMethod https://autonomous-career-agent-cloud.pages.dev/api/health
Invoke-RestMethod https://autonomous-career-agent-cloud.pages.dev/api/dashboard
Invoke-RestMethod https://autonomous-career-agent-cloud.pages.dev/api/preferences
```

`/api/dashboard` should return JSON with numeric counters. `applications_submitted` counts only statuses `submitted`, `confirmed`, `applied`, and `external_submitted`; `applications_total` counts records that reached a recognised application workflow, rather than counting every low-match/experience-rejected job as an application. The Find Jobs endpoint uses the jobs inventory and groups it by workflow outcome.

## Expected behavior / limits

- Dashboard GET APIs are public as requested. This also means any data exposed by those APIs is publicly readable; do not sync data that should remain private.
- Resume files/content that the app publishes to D1 can be accessible to public pages. Do not sync master/tailored resumes if you do not want them public.
- Free GitHub-hosted runner jobs are temporary and limited. The cloud runner is capped at 1–5 target applications per run in this configuration; it is not a permanent browser worker.
- A successful local build and static tests do not prove that Cloudflare settings, D1 migrations, GitHub secrets, GitHub dispatch, or real portal login are correct. Run the endpoint checks above after deployment.
