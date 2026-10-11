"""PostgreSQL queue and shared-state bridge for split cloud deployment.

The legacy local mode does not import or use this module. In cloud queue mode,
PostgreSQL is the source of truth for tasks, browser sessions, worker heartbeat,
and a compressed snapshot of the project's existing SQLite databases/resume files.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

_PORTALS = {"naukri", "indeed", "linkedin", "shine", "timesjobs", "glassdoor"}
_SCHEMA_LOCK_ID = 6724912201
_DATA_MUTATION_LOCK_ID = 6724912203
_SYNC_LOCK = threading.RLock()
_LAST_APPLIED_GENERATION = -1
_MAX_SNAPSHOT_BYTES = int(os.getenv("CAREER_AGENT_MAX_SNAPSHOT_BYTES", str(96 * 1024 * 1024)))


def connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required when CAREER_AGENT_EXECUTION_MODE=queue")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=8, application_name="autonomous-career-agent")


def ensure_schema() -> None:
    """Create queue/snapshot tables. Safe to call from both API and worker at boot."""
    with connect() as con:
        con.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_ID,))
        con.execute("""
            CREATE TABLE IF NOT EXISTS cloud_portal_tasks (
                task_id TEXT PRIMARY KEY,
                portal TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed','cancelled')),
                requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                heartbeat_at TIMESTAMPTZ,
                worker_id TEXT,
                child_pid INTEGER,
                returncode INTEGER,
                cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
                continue_requested BOOLEAN NOT NULL DEFAULT FALSE,
                human_verification BOOLEAN NOT NULL DEFAULT FALSE,
                log_tail TEXT NOT NULL DEFAULT '',
                error TEXT
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS cloud_portal_tasks_status_idx ON cloud_portal_tasks(status, requested_at)")
        con.execute("CREATE INDEX IF NOT EXISTS cloud_portal_tasks_portal_idx ON cloud_portal_tasks(portal, requested_at DESC)")
        con.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS cloud_one_active_task_per_portal
            ON cloud_portal_tasks(portal) WHERE status IN ('queued','running')
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS cloud_browser_sessions (
                portal TEXT PRIMARY KEY,
                storage_state JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS cloud_service_state (
                state_key TEXT PRIMARY KEY,
                state_value JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS cloud_shared_snapshot (
                singleton_id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (singleton_id = 1),
                generation BIGINT NOT NULL,
                sha256 TEXT NOT NULL,
                bundle BYTEA NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)


def _task_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for key in ("requested_at", "started_at", "finished_at", "heartbeat_at"):
        value = result.get(key)
        if value is not None and hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result


def enqueue_portal(portal: str) -> dict[str, Any]:
    portal = portal.strip().lower()
    if portal not in _PORTALS:
        raise ValueError(f"unknown portal: {portal}")
    with connect() as con:
        con.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("career-agent-portal:" + portal,))
        existing = con.execute(
            "SELECT * FROM cloud_portal_tasks WHERE portal=%s AND status IN ('queued','running') ORDER BY requested_at DESC LIMIT 1",
            (portal,),
        ).fetchone()
        if existing:
            out = _task_dict(existing)
            out["already_active"] = True
            return out
        task_id = str(uuid4())
        row = con.execute(
            "INSERT INTO cloud_portal_tasks(task_id,portal,status) VALUES(%s,%s,'queued') RETURNING *",
            (task_id, portal),
        ).fetchone()
        out = _task_dict(row)
        out["already_active"] = False
        return out


def claim_next_task(worker_id: str) -> dict[str, Any] | None:
    # Serialize the transition to running against API-side SQLite mutations. This
    # closes the race where an API write checks the queue just before a worker claims.
    with connect() as con:
        con.execute("SELECT pg_advisory_lock(%s)", (_DATA_MUTATION_LOCK_ID,))
        row = con.execute(
            "SELECT task_id FROM cloud_portal_tasks WHERE status='queued' ORDER BY requested_at, portal FOR UPDATE SKIP LOCKED LIMIT 1"
        ).fetchone()
        if not row:
            return None
        task = con.execute(
            "UPDATE cloud_portal_tasks SET status='running', started_at=NOW(), heartbeat_at=NOW(), worker_id=%s, cancel_requested=FALSE, continue_requested=FALSE, error=NULL WHERE task_id=%s AND status='queued' RETURNING *",
            (worker_id, row["task_id"]),
        ).fetchone()
        return _task_dict(task)


def acquire_shared_mutation_lock():
    """Hold the distributed data lock across an API mutation and snapshot upload."""
    con = connect()
    con.execute("SELECT pg_advisory_lock(%s)", (_DATA_MUTATION_LOCK_ID,))
    return con


def release_shared_mutation_lock(con) -> None:
    try:
        con.execute("SELECT pg_advisory_unlock(%s)", (_DATA_MUTATION_LOCK_ID,))
    finally:
        con.close()


def update_task(task_id: str, **fields: Any) -> None:
    allowed = {
        "status", "heartbeat_at", "child_pid", "returncode", "cancel_requested",
        "continue_requested", "human_verification", "log_tail", "error", "started_at", "finished_at",
    }
    updates = [(k, v) for k, v in fields.items() if k in allowed]
    if not updates:
        return
    assignments_parts: list[str] = []
    values: list[Any] = []
    for key, value in updates:
        if value == "NOW()":
            assignments_parts.append(f"{key}=NOW()")
        else:
            assignments_parts.append(f"{key}=%s")
            values.append(value)
    assignments = ", ".join(assignments_parts)
    with connect() as con:
        con.execute(f"UPDATE cloud_portal_tasks SET {assignments} WHERE task_id=%s", (*values, task_id))


def task_control(task_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute(
            "SELECT task_id,portal,status,cancel_requested,continue_requested FROM cloud_portal_tasks WHERE task_id=%s",
            (task_id,),
        ).fetchone()
    return dict(row) if row else None


def active_tasks() -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM cloud_portal_tasks WHERE status IN ('queued','running') ORDER BY requested_at"
        ).fetchall()
    return [_task_dict(r) for r in rows]


def recent_tasks(limit: int = 12) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    with connect() as con:
        rows = con.execute("SELECT * FROM cloud_portal_tasks ORDER BY requested_at DESC LIMIT %s", (limit,)).fetchall()
    return [_task_dict(r) for r in rows]


def get_task(task_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM cloud_portal_tasks WHERE task_id=%s", (task_id,)).fetchone()
    return _task_dict(row)


def request_cancel_all() -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute("""
            UPDATE cloud_portal_tasks
            SET status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,
                cancel_requested=CASE WHEN status='running' THEN TRUE ELSE cancel_requested END,
                finished_at=CASE WHEN status='queued' THEN NOW() ELSE finished_at END
            WHERE status IN ('queued','running')
            RETURNING *
        """).fetchall()
    return [_task_dict(r) for r in rows]


def request_indeed_continue() -> bool:
    with connect() as con:
        row = con.execute(
            "UPDATE cloud_portal_tasks SET continue_requested=TRUE WHERE portal='indeed' AND status='running' AND human_verification=TRUE RETURNING task_id"
        ).fetchone()
    return row is not None


def _session_cipher():
    import base64
    import hashlib
    from cryptography.fernet import Fernet
    key = os.getenv("CAREER_AGENT_SESSION_ENCRYPTION_KEY", "").strip()
    if len(key) < 32:
        raise RuntimeError("CAREER_AGENT_SESSION_ENCRYPTION_KEY must contain at least 32 characters")
    # Render-generated secrets are not guaranteed to be Fernet-formatted. Derive
    # a fixed-size Fernet key from the high-entropy shared secret instead.
    derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode("utf-8")).digest())
    return Fernet(derived)


def save_browser_session(portal: str, state: dict[str, Any]) -> None:
    if portal not in _PORTALS:
        raise ValueError("unknown portal")
    plaintext = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encrypted = _session_cipher().encrypt(plaintext).decode("ascii")
    # JSONB stores the Fernet token as a JSON string; cookie/localStorage content is
    # never persisted as plaintext in PostgreSQL.
    with connect() as con:
        con.execute("""
            INSERT INTO cloud_browser_sessions(portal,storage_state,updated_at)
            VALUES(%s,%s,NOW())
            ON CONFLICT(portal) DO UPDATE SET storage_state=EXCLUDED.storage_state, updated_at=NOW()
        """, (portal, Jsonb(encrypted)))


def list_browser_sessions() -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute("SELECT portal,storage_state,updated_at FROM cloud_browser_sessions").fetchall()
    cipher = _session_cipher() if rows else None
    result = []
    for row in rows:
        token = row["storage_state"]
        if not isinstance(token, str):
            raise RuntimeError(f"Stored browser session for {row['portal']} is not encrypted; re-import that portal session")
        try:
            state = json.loads(cipher.decrypt(token.encode("ascii")).decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Could not decrypt browser session for {row['portal']}; check shared encryption key") from exc
        result.append({"portal": row["portal"], "storage_state": state, "updated_at": row["updated_at"]})
    return result


def set_service_state(key: str, value: dict[str, Any]) -> None:
    with connect() as con:
        con.execute("""
            INSERT INTO cloud_service_state(state_key,state_value,updated_at) VALUES(%s,%s,NOW())
            ON CONFLICT(state_key) DO UPDATE SET state_value=EXCLUDED.state_value,updated_at=NOW()
        """, (key, Jsonb(value)))


def get_service_state(key: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT state_value,updated_at FROM cloud_service_state WHERE state_key=%s", (key,)).fetchone()
    if not row:
        return None
    value = dict(row["state_value"] or {})
    stamp = row["updated_at"]
    value["_updated_at"] = stamp.isoformat() if stamp else None
    value["_fresh"] = bool(stamp and (datetime.now(timezone.utc) - stamp).total_seconds() < 45)
    return value


def _shared_paths(*, include_files: bool = True) -> list[Path]:
    candidates: list[Path] = [ROOT / "applications.db"]
    for portal in sorted(_PORTALS):
        candidates.append(ROOT / "platforms" / portal / "applications.db")
    # These files contain user-specific answers and generated resumes. The worker and
    # API need a common view even though Render disks are per-service.
    for name in ("profile.json", "role_config.json", "resume_content_bank.json"):
        candidates.append(ROOT / name)
    if include_files:
        for folder in (ROOT / "resume_versions",):
            if folder.is_dir():
                candidates.extend(p for p in folder.rglob("*") if p.is_file())
        for portal in sorted(_PORTALS):
            folder = ROOT / "platforms" / portal / "resume"
            if folder.is_dir():
                candidates.extend(p for p in folder.rglob("*") if p.is_file())
    return sorted({p for p in candidates if p.is_file()}, key=lambda p: str(p))


def _make_bundle(*, include_files: bool = True) -> bytes:
    """Build a consistent compressed bundle; SQLite files use SQLite's backup API."""
    tmpdir = Path(tempfile.mkdtemp(prefix="career-agent-snapshot-"))
    output = io.BytesIO()
    try:
        prepared: list[tuple[Path, Path]] = []
        for path in _shared_paths(include_files=include_files):
            try:
                rel = path.relative_to(ROOT)
            except ValueError:
                continue
            if path.name == "applications.db":
                target = tmpdir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as source, sqlite3.connect(target) as dest:
                        source.backup(dest, pages=128, sleep=0.05)
                    prepared.append((target, rel))
                    continue
                except sqlite3.Error:
                    # Some seeded files may not be a valid SQLite file yet. Copying the
                    # file is a fallback; the next regular snapshot retries the backup.
                    pass
            prepared.append((path, rel))
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
            for source, rel in prepared:
                try:
                    archive.write(source, arcname=rel.as_posix())
                except OSError:
                    continue
        bundle = output.getvalue()
        if len(bundle) > _MAX_SNAPSHOT_BYTES:
            raise RuntimeError(
                f"Shared project snapshot is {len(bundle):,} bytes; limit is {_MAX_SNAPSHOT_BYTES:,}. "
                "Move large resume archives to object storage or increase CAREER_AGENT_MAX_SNAPSHOT_BYTES."
            )
        return bundle
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def push_shared_snapshot(*, include_files: bool = True) -> int:
    # Encrypt the full snapshot too: it includes personal profile data, application
    # history, and generated resumes, not just the already-encrypted portal cookies.
    bundle = _session_cipher().encrypt(_make_bundle(include_files=include_files))
    digest = hashlib.sha256(bundle).hexdigest()
    with connect() as con:
        con.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_ID + 1,))
        row = con.execute("""
            INSERT INTO cloud_shared_snapshot(singleton_id,generation,sha256,bundle,updated_at)
            VALUES(1,1,%s,%s,NOW())
            ON CONFLICT(singleton_id) DO UPDATE SET
                generation=cloud_shared_snapshot.generation+1,
                sha256=EXCLUDED.sha256,bundle=EXCLUDED.bundle,updated_at=NOW()
            RETURNING generation
        """, (digest, bundle)).fetchone()
        return int(row["generation"])


def initialize_shared_snapshot() -> int:
    """Seed initial shared state once; simultaneous API/worker startup is safe."""
    with connect() as con:
        con.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_ID + 1,))
        row = con.execute("SELECT generation FROM cloud_shared_snapshot WHERE singleton_id=1").fetchone()
        if row:
            return int(row["generation"])
        bundle = _session_cipher().encrypt(_make_bundle())
        digest = hashlib.sha256(bundle).hexdigest()
        con.execute(
            "INSERT INTO cloud_shared_snapshot(singleton_id,generation,sha256,bundle,updated_at) VALUES(1,1,%s,%s,NOW()) ON CONFLICT DO NOTHING",
            (digest, bundle),
        )
        row = con.execute("SELECT generation FROM cloud_shared_snapshot WHERE singleton_id=1").fetchone()
        return int(row["generation"])


def sync_shared_from_store(force: bool = False) -> int:
    """Apply only newer snapshots, replacing each file atomically after safe validation."""
    global _LAST_APPLIED_GENERATION
    with _SYNC_LOCK:
        with connect() as con:
            row = con.execute("SELECT generation,sha256,bundle FROM cloud_shared_snapshot WHERE singleton_id=1").fetchone()
        if not row:
            return initialize_shared_snapshot()
        generation = int(row["generation"])
        if not force and generation <= _LAST_APPLIED_GENERATION:
            return generation
        encrypted_bundle = bytes(row["bundle"])
        if hashlib.sha256(encrypted_bundle).hexdigest() != row["sha256"]:
            raise RuntimeError("Shared-state snapshot checksum mismatch")
        try:
            bundle = _session_cipher().decrypt(encrypted_bundle)
        except Exception as exc:
            raise RuntimeError("Could not decrypt the shared-state snapshot; verify the shared encryption key") from exc
        stage = Path(tempfile.mkdtemp(prefix="career-agent-restore-", dir=str(ROOT)))
        try:
            with zipfile.ZipFile(io.BytesIO(bundle), "r") as archive:
                for info in archive.infolist():
                    member = PurePosixPath(info.filename)
                    if member.is_absolute() or ".." in member.parts or not member.parts:
                        raise RuntimeError("Unsafe path inside shared-state snapshot")
                    destination = (stage / Path(*member.parts)).resolve()
                    if not destination.is_relative_to(stage.resolve()):
                        raise RuntimeError("Unsafe path inside shared-state snapshot")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info, "r") as src, destination.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
            for staged in stage.rglob("*"):
                if not staged.is_file():
                    continue
                rel = staged.relative_to(stage)
                target = ROOT / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp_target = target.with_name(target.name + ".cloudsync.tmp")
                shutil.copy2(staged, tmp_target)
                os.replace(tmp_target, target)
            _LAST_APPLIED_GENERATION = generation
            return generation
        finally:
            shutil.rmtree(stage, ignore_errors=True)



def recover_stale_tasks(stale_seconds: int = 120) -> int:
    """Fail tasks left running by a worker that crashed or was redeployed."""
    with connect() as con:
        rows = con.execute("""
            UPDATE cloud_portal_tasks
            SET status='failed', finished_at=NOW(), child_pid=NULL,
                error='Worker heartbeat expired; run was not automatically resubmitted to avoid duplicate applications.'
            WHERE status='running'
              AND (heartbeat_at IS NULL OR heartbeat_at < NOW() - (%s * INTERVAL '1 second'))
            RETURNING task_id
        """, (max(30, int(stale_seconds)),)).fetchall()
    return len(rows)

def active_task_count() -> int:
    with connect() as con:
        row = con.execute("SELECT COUNT(*) AS n FROM cloud_portal_tasks WHERE status IN ('queued','running')").fetchone()
    return int(row["n"])
