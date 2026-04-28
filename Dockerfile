# Build: dependencies only. No database exists during `docker build`.
# Migrations run in entrypoint.sh at container start when env vars are injected.
FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN pip install --no-cache-dir uv

# Full tree (see .dockerignore) so `uv sync` can resolve the project if needed
COPY . .

RUN chmod +x build.sh entrypoint.sh && ./build.sh

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
