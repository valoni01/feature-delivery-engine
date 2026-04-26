#!/usr/bin/env bash
set -o errexit

pip install uv
uv sync --no-dev
uv run alembic upgrade head
