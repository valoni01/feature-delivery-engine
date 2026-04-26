#!/usr/bin/env bash
set -o errexit

pip install uv
uv sync --no-dev
