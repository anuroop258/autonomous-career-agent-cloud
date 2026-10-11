# Cloud deployment changes — worker/API split

This revision replaces the earlier single-service cloud candidate with a separate API and background-worker architecture while keeping the portal automation entrypoint (`main.py <portal>`) and portal engines intact.

## Added

- `cloud_queue.py`: PostgreSQL-backed durable portal task queue, per-portal active-task guard, cancellation/Indeed continuation flags, worker/service heartbeat, encrypted session storage, and compressed snapshot synchronization for existing SQLite DBs and generated resume files.
- `cloud_worker.py`: background worker that starts persistent Linux Chromium on CDP ports 9222/9232, applies imported sessions, executes queued portal agents, captures logs and process status, publishes shared snapshots, and avoids automatic retries after a worker crash.
- `render.yaml`: `career-api` web service, `career-worker` background worker, PostgreSQL database, worker-only persistent disk, and shared generated secret group.
- Shared-state advisory lock: prevents the API's SQLite writes from racing a worker task claim; the API returns 409 for shared-data edits while an agent run is active.

## Updated

- `webapp/backend/main.py`: cloud queue mode branches automation start/stop/status, portal launch/CDP state, session import, Indeed continue, and log endpoints to the shared worker/queue state. Legacy local mode remains on its prior code path.
- `docker-entrypoint.sh`: preserves legacy persistent SQLite setup only outside queue mode; cloud API does not create its own private persistent-disk database.
- `requirements.txt`: adds PostgreSQL driver and Fernet cryptography dependency.
- `DEPLOY_CLOUD.md`: updated for the actual two-service architecture and remaining validation.

## Known boundaries

- The shared snapshot bridge stores compressed SQLite/resume snapshots inside PostgreSQL. It has a 96 MiB compressed-bundle default limit and is intended for this project's current footprint, not unbounded media storage. Large-scale deployment should move resume artifacts to S3-compatible object storage and ultimately migrate application tables to a shared relational data model.
- Cloud portal behavior cannot be fully proven without a live Render deployment and valid portal sessions. Each portal needs a supervised end-to-end test before unattended use.

- Shared SQLite/resume snapshots are encrypted before storage in PostgreSQL; the same high-entropy environment secret is used to derive the encryption key.
