-- Associates runner task rows with the operation being performed. Kept separate so
-- an existing tasks table can be upgraded without destructive ALTER TABLE statements.
CREATE TABLE IF NOT EXISTS task_details (
  task_id TEXT PRIMARY KEY,
  operation TEXT NOT NULL DEFAULT 'job_search' CHECK (operation IN ('job_search','tailor_resume')),
  job_ref TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT '',
  FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);

-- CareerAgent public dashboard data migration. Safe to run repeatedly.
-- Keep all private browser cookies/session JSON out of these public tables.
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  job_ref TEXT NOT NULL UNIQUE,
  platform TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '',
  job_key TEXT DEFAULT '',
  title TEXT NOT NULL DEFAULT 'Unknown role',
  company TEXT NOT NULL DEFAULT 'Unknown_Company',
  location TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  discovered_at TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT '',
  match_score REAL,
  eligible INTEGER,
  matched_skills TEXT NOT NULL DEFAULT '[]',
  missing_skills TEXT NOT NULL DEFAULT '[]',
  application_id INTEGER,
  application_platform TEXT,
  application_status TEXT,
  resume_version_id INTEGER,
  resume_pdf_available INTEGER NOT NULL DEFAULT 0,
  application_route TEXT NOT NULL DEFAULT 'unknown',
  status TEXT NOT NULL DEFAULT 'discovered'
);
CREATE INDEX IF NOT EXISTS jobs_recent_idx ON jobs(discovered_at DESC);
CREATE INDEX IF NOT EXISTS jobs_platform_idx ON jobs(platform);
CREATE INDEX IF NOT EXISTS jobs_score_idx ON jobs(match_score DESC);
CREATE INDEX IF NOT EXISTS jobs_eligible_idx ON jobs(eligible);

CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY,
  application_ref TEXT NOT NULL UNIQUE,
  candidate_id TEXT NOT NULL DEFAULT 'public',
  job_id INTEGER NOT NULL,
  platform TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'discovered',
  resume_version_id INTEGER,
  submitted_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT 'Unknown role',
  company TEXT NOT NULL DEFAULT 'Unknown_Company',
  location TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  eligible INTEGER,
  resume_pdf_available INTEGER NOT NULL DEFAULT 0,
  application_route TEXT NOT NULL DEFAULT 'unknown',
  description TEXT NOT NULL DEFAULT '',
  match_score REAL,
  matched_skills TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS applications_recent_idx ON applications(created_at DESC);
CREATE INDEX IF NOT EXISTS applications_status_idx ON applications(status);
CREATE INDEX IF NOT EXISTS applications_platform_idx ON applications(platform);

CREATE TABLE IF NOT EXISTS custom_qa (
  id INTEGER PRIMARY KEY,
  question TEXT NOT NULL UNIQUE,
  answer TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS qa (
  id INTEGER PRIMARY KEY,
  job_url TEXT NOT NULL DEFAULT '',
  question TEXT NOT NULL DEFAULT '',
  answer TEXT NOT NULL DEFAULT '',
  field TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS app_config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  config_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS app_documents (
  doc_key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS resume_versions (
  id INTEGER PRIMARY KEY,
  job_ref TEXT NOT NULL DEFAULT '',
  platform TEXT NOT NULL DEFAULT '',
  company TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT '',
  job_url TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  report_json TEXT NOT NULL DEFAULT '{}',
  pdf_available INTEGER NOT NULL DEFAULT 0,
  pdf_filename TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS resume_versions_job_idx ON resume_versions(job_ref);
CREATE TABLE IF NOT EXISTS resume_files (
  file_key TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
  content_b64 TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS recruiters (
  id INTEGER PRIMARY KEY,
  company TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
  email TEXT, profile_url TEXT, source TEXT NOT NULL DEFAULT '', confidence REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS outreach (
  id INTEGER PRIMARY KEY,
  job_id INTEGER, recruiter_id INTEGER, channel TEXT NOT NULL DEFAULT 'email',
  subject TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft',
  sent_at TEXT, follow_up_at TEXT, created_at TEXT NOT NULL DEFAULT '',
  job_title TEXT, company TEXT, recruiter_name TEXT, recruiter_email TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'application', ref_id INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending', summary TEXT NOT NULL DEFAULT '', note TEXT,
  requested_at TEXT NOT NULL DEFAULT '', decided_at TEXT
);
CREATE TABLE IF NOT EXISTS log_events (
  id INTEGER PRIMARY KEY,
  run_id TEXT, event_type TEXT NOT NULL DEFAULT '', platform TEXT, job_id INTEGER,
  application_id INTEGER, payload_json TEXT, created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS log_events_recent_idx ON log_events(created_at DESC);
