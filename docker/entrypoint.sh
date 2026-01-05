#!/bin/sh
set -eu

if [ "${DB_WAIT:-1}" = "1" ]; then
  python /app/docker/wait_for_db.py
fi

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "[entrypoint] Running alembic migrations (upgrade head)..."
  alembic upgrade head
fi

exec "$@"
