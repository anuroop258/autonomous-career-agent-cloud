# Autonomous Career Agent — independent cloud deployment

This branch uses **separate Render API and background-worker services**. The dashboard/API does not launch local agent subprocesses. A dedicated Linux worker owns Chromium and executes the existing `main.py <portal>` agent entrypoint; PostgreSQL coordinates tasks and publishes shared project state.

## Architecture

- **`career-api`** serves the built React/Vite dashboard and FastAPI endpoints. It validates requests and stores run requests in PostgreSQL.
- **`career-worker`** is a Render Background Worker. It starts persistent headless Chromium instances on CDP ports `9222` (Naukri/Indeed/Shine/TimesJobs/Glassdoor) and `9232` (LinkedIn), claims queued portal tasks, runs the current portal agent without rewriting its application logic, and records status and log tails.
- **`career-agent-db`** is PostgreSQL. It stores the durable portal queue, task status, worker heartbeat, encrypted browser-session exports, and encrypted/compressed snapshots of the current SQLite application databases and generated resume files. The code caps a compressed snapshot at 96 MiB by default; increase `CAREER_AGENT_MAX_SNAPSHOT_BYTES` only if you have checked database storage and transfer cost. For large-scale resume/media storage, migrate generated files to a dedicated object-storage bucket.
- The worker's **2 GB persistent disk** at `/data` holds Chromium user profiles. Render disks are isolated to one service, so the API does not try to open the worker's disk.
- Browser-session JSON and shared data snapshots are Fernet-encrypted before being stored in PostgreSQL. The common `career-agent-secrets` environment group supplies the API key and a high-entropy encryption secret to both services; the application derives its Fernet key from that secret, so Render's generated value does not need to use a special encoding.

## 1. Keep the repository private

1. Create a **private** GitHub repository for this project and push this package to its deployment branch.
2. Do not publish `.env` files, API keys, profile/resume details, SQLite databases, browser cookies, Playwright storage-state exports, or logs in a public repository.
3. Before the first production run, review the seed `profile.json`, role configs, resume content, and databases included in the repository. These can contain personal information and will seed the shared snapshot the first time the services start.

## 2. Create the Render services

1. In Render, select **New + → Blueprint** and connect the private repository.
2. Render reads `render.yaml` and creates `career-api`, `career-worker`, the `career-agent-db` PostgreSQL database, and the shared `career-agent-secrets` environment group.
3. Keep the `CAREER_AGENT_API_KEY` and `CAREER_AGENT_SESSION_ENCRYPTION_KEY` values private. The environment group ensures the API and worker use the same encryption key; do not rotate it after importing sessions unless you intend to re-import those sessions.
4. Wait until both services deploy. The worker log should show `ready ... polling PostgreSQL queue`. The API health endpoint is `/api/health`; the dashboard's system status should report the worker online and Chromium ports connected.
5. Save the public API/dashboard URL and API key in your own password manager. Do not put the API key in source control or issue comments.

The Blueprint uses paid web/worker compute, a PostgreSQL database, and a 2 GB worker disk. Confirm current plan pricing before creating the resources.

## 3. Import portal sessions

Cloud Chromium is headless; it does not use the Chrome session on your PC directly. Export only the portal session you need from your logged-in local Chrome and upload it over HTTPS:

```powershell
python tools/export_cloud_session.py naukri --api-url https://YOUR-API.onrender.com --api-key YOUR_API_KEY
python tools/export_cloud_session.py indeed --api-url https://YOUR-API.onrender.com --api-key YOUR_API_KEY
python tools/export_cloud_session.py linkedin --api-url https://YOUR-API.onrender.com --api-key YOUR_API_KEY
```

Supported portal names: `naukri`, `indeed`, `linkedin`, `shine`, `timesjobs`, and `glassdoor`. Use only the portal commands you need. The session token is encrypted in PostgreSQL and the worker applies it to the relevant headless Chromium context. Re-import after logout or session expiry. Some portals or external ATS sites may still require MFA or manual steps.

The cloud browser is headless; this package does not include a live VNC/noVNC screen for interacting with a challenge inside the worker. Do not attempt to bypass CAPTCHA or other portal security checks. If a portal requires a visible challenge, complete it in your local browser, export/import a fresh session, and resume only if the portal and workflow allow that safely. Test this process per portal before unattended use.

## 4. Start with one supervised portal

1. Open the dashboard and verify **System Status** shows the worker online and both CDP ports available.
2. Import one portal's session.
3. Launch/test that portal from the dashboard.
4. Start with **one portal and a small application target**. Watch the run status and log tail. Confirm the site is authenticated, job filtering is correct, application questions use the intended saved answers, and any resume upload is the right file before increasing the run size.
5. Test Stop while a run is active. For Indeed, test the human-verification continue button only after the dashboard indicates it is waiting for manual verification.

## Queue and data behavior

- Each requested portal run becomes a PostgreSQL task with a unique task ID. The worker claims tasks using row locking (`FOR UPDATE SKIP LOCKED`) and a per-portal active-task constraint to avoid two workers claiming the same portal run.
- Stop requests cancel queued tasks and flag the active subprocess for termination. A worker restart marks stale running tasks failed rather than blindly retrying them; this is intentional because automatic retry could submit an application twice.
- The worker publishes SQLite database snapshots periodically during runs and full snapshots after completion. The API refreshes its local read view from newer snapshots, so new application records and generated resume files become visible in the dashboard across the service boundary.
- To avoid conflicting SQLite writes, API actions that modify shared application/QA/resume state return HTTP `409` while an agent task is queued or running. Retry those edits after the run is finished. Dashboard reads and status polling remain available.
- The worker's profile directory is persistent on `/data`; queue state and cross-service application data are stored in PostgreSQL. The API does not depend on a shared Render disk.

## 5. Remaining production validation

This is a **cloud-ready candidate package, not a claim that a live job application has been proven end-to-end**. Before relying on it, check the following against your deployed services:

- Docker build and both Render services start successfully.
- Queue round-trip: submit one task, confirm the worker claims it, and confirm the task ends as completed/failed/cancelled with logs.
- A task survives API restarts, and a worker crash produces a stale-task failure rather than a silent stuck state.
- The dashboard can see a new application and a generated resume after the worker publishes a snapshot.
- Session import is encrypted in PostgreSQL and survives a worker restart; the portal session itself may expire independently.
- Headless Chromium compatibility for each portal, job-search filtering, duplicate-submission gates, question filling, resume uploads, external ATS pages, stop behavior, and human-verification flows. This package has no interactive remote browser viewer; a portal challenge may require exporting/importing a fresh local session.
- Generated snapshot stays under the configured limit and PostgreSQL storage usage is acceptable. Move large files to object storage before growth approaches the cap.
- Review security and portal terms before enabling unattended applications. A dashboard API key alone is not a substitute for careful access control, secret management, and supervised validation.

## Troubleshooting

- **Worker offline / CDP unavailable:** check `career-worker` logs first. The API intentionally refuses to enqueue a run if the worker heartbeat or Chromium ports are missing.
- **Queue database unavailable:** check `DATABASE_URL` binding and Render PostgreSQL health. Both API and worker must use the same database.
- **Could not decrypt stored session:** verify `CAREER_AGENT_SESSION_ENCRYPTION_KEY` matches in both services. If the key was rotated, re-import the affected sessions.
- **Shared snapshot limit exceeded:** set a larger `CAREER_AGENT_MAX_SNAPSHOT_BYTES` only after assessing PostgreSQL capacity, or move resume artifacts to object storage.
- **Task failed after worker restart:** inspect the stored task error and latest logs. Failed tasks are not automatically resubmitted to avoid duplicate application submissions.

## Useful Render documentation

- [Blueprints and service configuration](https://render.com/docs/blueprint-spec)
- [Background workers](https://render.com/docs/background-workers)
- [Persistent disks and their service-local scope](https://render.com/docs/disks)
- [PostgreSQL](https://render.com/docs/postgresql)
