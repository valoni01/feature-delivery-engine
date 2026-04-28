#!/usr/bin/env bash
# Run at container *start* only — not during image build. Requires DATABASE_URL or PG* vars.
set -euo pipefail
cd /app
uv run alembic upgrade head
exec uv run uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
