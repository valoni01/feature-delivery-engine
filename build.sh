#!/usr/bin/env bash
# Install dependencies only. Do not run `alembic` here: the image build has no DATABASE_URL
# and nothing listens on localhost:5432. Run migrations at container start (see entrypoint.sh
# and Procfile).
set -o errexit

pip install uv
uv sync --no-dev
