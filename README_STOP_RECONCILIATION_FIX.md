# CareerAgent stop/reconciliation fix

Overlay these files into the existing repository root. This fix addresses the cloud-runner lifecycle issue where Cloudflare D1 stayed in `stopping` after GitHub Actions had finished or been cancelled.

Included changes:
- `functions/api/automation/stop.js`: records stop intent and requests real GitHub Actions run cancellation using the stored run ID, with a task-ID lookup fallback.
- `functions/api/automation/status.js`: reconciles D1 with GitHub run state while the dashboard polls, retries cancellation for stopping tasks, and marks terminal states.
- `functions/api/worker/report.js`: records GitHub run IDs and prevents a late `running` callback from reverting `stopping` or a terminal state; if a stop was requested before the run ID arrived, it cancels once the callback provides the ID.
- `tools/report_cloud_status.py` and `.github/workflows/free-cloud-run.yml`: report `GITHUB_RUN_ID` to D1 immediately after checkout and report workflow cancellation.

Requirements already used by the app: Cloudflare Production secrets `GH_DISPATCH_TOKEN`, `DASHBOARD_API_KEY` (or `CLOUD_CONTROL_API_KEY`) and vars `GH_REPO_OWNER`, `GH_REPO_NAME`; the GitHub token needs permission to read workflow runs and cancel Actions runs. The workflow's `CLOUD_CONTROL_API_BASE` variable and `CLOUD_CONTROL_API_KEY` secret must remain configured.

This patch does not edit profile/resume files or any local database. After overlaying, run syntax checks and the existing test file, then stage only the included files.
