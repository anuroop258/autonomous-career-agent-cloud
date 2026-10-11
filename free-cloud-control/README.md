# Free Cloud Control Page

Cloudflare Pages Functions + D1 API for a cardless, on-demand GitHub Actions runner.
This intentionally provides a small run-control page rather than pretending to be the
full React/FastAPI analytics dashboard.

## Cloudflare Pages settings

- Root directory: `free-cloud-control`
- Build command: leave blank
- Build output directory: `public`
- Add a D1 database binding named `DB` and bind it to the `career-agent-control` D1 database.
- Run `schema.sql` in the D1 console before using the page.

Set these Pages environment variables/secrets in Settings → Variables and Secrets:

- `DASHBOARD_API_KEY` (secret): strong random key, 32+ random bytes.
- `GH_DISPATCH_TOKEN` (secret): GitHub fine-grained PAT with **Actions: Read and write** on the source repository only.
- `GH_REPO_OWNER`: `anuroop258`
- `GH_REPO_NAME`: `autonomous-career-agent-cloud`
- `GH_WORKFLOW_FILE`: `free-cloud-run.yml`
- `CORS_ORIGIN`: the Pages URL, if you later call the API from a different origin; otherwise leave unset.

The same `DASHBOARD_API_KEY` value must be added to the GitHub repository as the Actions secret
`CLOUD_CONTROL_API_KEY`. Set repository variable `CLOUD_CONTROL_API_BASE` to the deployed Pages
URL, e.g. `https://your-project.pages.dev`.
