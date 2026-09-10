#!/bin/sh
# Container entrypoint.
#
# Migrations are opt-in. Running them automatically on every container start
# means N replicas racing the same ALTER on deploy, so the default is to leave
# them to an explicit release step. Set RUN_MIGRATIONS=1 for single-instance
# platforms where that is the convenient path.
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    echo "Running database migrations..."
    alembic upgrade head
fi

# PORT is injected by Railway, Fly and Cloud Run. The HEALTHCHECK reads the
# same variable, so the two cannot drift; 8000 is the shared fallback and the
# frontend's default proxy target.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --proxy-headers \
    --forwarded-allow-ips '*'
