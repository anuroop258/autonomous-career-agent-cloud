-- Base task-control schema. Safe to apply when the table already exists.
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  portal TEXT NOT NULL CHECK (portal IN ('naukri','indeed','linkedin','shine','timesjobs','glassdoor')),
  max_jobs INTEGER NOT NULL CHECK (max_jobs BETWEEN 1 AND 5),
  status TEXT NOT NULL CHECK (status IN ('queued','running','stopping','completed','failed','cancelled')),
  requested_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  github_run_id TEXT,
  stop_requested INTEGER NOT NULL DEFAULT 0,
  exit_code INTEGER,
  error TEXT,
  log_tail TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_recent_idx ON tasks(requested_at DESC);
CREATE INDEX IF NOT EXISTS tasks_status_idx ON tasks(status);
