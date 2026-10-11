#!/bin/sh
set -e

# Never run on the public internet without a key.
if [ "${#CAREER_AGENT_API_KEY}" -lt 16 ]; then
  echo "REFUSING TO START: set CAREER_AGENT_API_KEY to a secret of at least 16 characters." >&2
  exit 1
fi

# Local/legacy deployment keeps its historical single-service SQLite behavior.
# Split cloud mode uses PostgreSQL as the queue/snapshot source of truth; the API
# container must not create a private /data SQLite database that the worker cannot see.
if [ "${CAREER_AGENT_EXECUTION_MODE:-}" != "queue" ]; then
  DATA_DIR="${DATA_DIR:-/data}"
  if mkdir -p "$DATA_DIR" 2>/dev/null && [ -w "$DATA_DIR" ]; then
    [ -f "$DATA_DIR/applications.db" ] || cp /app/applications.db "$DATA_DIR/applications.db"
    ln -sf "$DATA_DIR/applications.db" /app/applications.db
    echo "Database: $DATA_DIR/applications.db (persistent)"
  else
    echo "WARNING: no writable $DATA_DIR - using the bundled database; changes are lost on redeploy." >&2
  fi
fi

exec python -m uvicorn webapp.backend.main:app --host 0.0.0.0 --port "${PORT:-10000}"
