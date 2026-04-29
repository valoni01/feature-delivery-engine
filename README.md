# FDE Backend

FastAPI backend for the Feature Delivery Engine — an AI-powered pipeline that takes a Feature Requirement Document (FRD) from draft to pull request.

## How It Works

A workflow moves through a LangGraph pipeline with human-in-the-loop support:

```
evaluate_frd ←→ wait_for_clarification (multi-round Q&A)
      ↓
finalize_frd → create_technical_design ←→ review_design (max 3 rework rounds)
                                                ↓
                                           plan_tasks
                                                ↓
                                       implement_tasks ←→ review_code (max 2 fix rounds)
                                                              ↓
                                                          create_pr → END
```

Each node is an LLM-powered agent that reads and writes to the shared pipeline state. Agents have access to codebase tools (read files, list directories, search, write files) and persist run metadata (tokens, duration, status) to the database.

## Tech Stack

- **Runtime:** Python 3.12+, FastAPI, Uvicorn
- **Database:** PostgreSQL with async SQLAlchemy + Alembic migrations
- **AI/LLM:** OpenAI API (GPT-4o default), LangGraph for pipeline orchestration
- **Observability:** OpenTelemetry (tracing), Sentry (error tracking)
- **Package manager:** uv

## Project Structure

```
app/
├── main.py                    # FastAPI app, CORS, telemetry, router mounts
├── agents/                    # LangGraph pipeline nodes
│   ├── base.py                # AgentRun tracking context manager + OTel spans
│   ├── state.py               # PipelineState TypedDict (shared graph state)
│   ├── frd_parser.py          # evaluate_frd, finalize_frd — FRD analysis with tool use
│   ├── tech_designer.py       # create_technical_design — architecture & file plans
│   ├── design_reviewer.py     # review_design — approve or request rework
│   ├── task_planner.py        # plan_tasks — break design into implementation tasks
│   ├── implementer.py         # implement_tasks — write code via tools
│   ├── code_reviewer.py       # review_code — approve or flag issues
│   ├── pr_creator.py          # create_pr — git commit, push, open PR via GitHub API
│   └── tools/
│       ├── codebase.py        # File read/write/search/list with path traversal guards
│       └── repo_manager.py    # Git clone/pull with token-injected HTTPS
├── core/
│   ├── config.py              # Pydantic Settings (env vars)
│   ├── db.py                  # Async SQLAlchemy engine + session factory
│   ├── llm.py                 # OpenAI client lifecycle
│   ├── logging.py             # Structured JSON logging
│   └── telemetry.py           # OpenTelemetry + Sentry init
├── integrations/
│   ├── models.py              # ServiceIntegration model
│   ├── routes.py              # Integration CRUD API
│   ├── github_client.py       # GitHub REST API client (list repos)
│   └── github_routes.py       # /github/repos endpoint
├── orchestration/
│   └── pipeline.py            # LangGraph StateGraph definition + MemorySaver checkpointer
├── services/
│   ├── models.py              # Service model
│   └── routes.py              # Service CRUD API
└── workflows/
    ├── models.py              # Workflow model
    └── routes.py              # Workflow API (create, run, clarify, transition, etc.)
```

## API Endpoints

All routes are prefixed with `/api/v1` unless noted.

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check |

### Workflows

| Method | Path | Description |
|--------|------|-------------|
| POST | `/workflows` | Create a new workflow (draft) |
| GET | `/workflows` | List workflows (filter by `service_id`, `status`) |
| GET | `/workflows/{id}` | Get a single workflow |
| PATCH | `/workflows/{id}` | Update workflow fields |
| POST | `/workflows/{id}/run` | Clone repo and start the pipeline |
| POST | `/workflows/{id}/clarify` | Submit answers to clarifying questions |
| POST | `/workflows/{id}/skip-clarification` | Skip remaining questions, finalize with available info |
| POST | `/workflows/{id}/retry-push` | Retry git push + PR creation |
| POST | `/workflows/{id}/transition` | Manually transition workflow status (validated FSM) |
| GET | `/workflows/{id}/agent-runs` | List all agent runs for a workflow |

### Services

| Method | Path | Description |
|--------|------|-------------|
| POST | `/services` | Create a service |
| GET | `/services` | List services |
| GET | `/services/{id}` | Get a service |
| PATCH | `/services/{id}` | Update a service |
| DELETE | `/services/{id}` | Soft-deactivate a service |

### Integrations

| Method | Path | Description |
|--------|------|-------------|
| POST | `/integrations` | Create an integration |
| GET | `/integrations` | List integrations (filter by `service_id`, `type`, `active_only`) |
| GET | `/integrations/{id}` | Get an integration |
| PATCH | `/integrations/{id}` | Update an integration |
| DELETE | `/integrations/{id}` | Soft-deactivate an integration |
| GET | `/github/repos` | List GitHub repos for the authenticated user |

## Database Models

| Table | Key Fields |
|-------|------------|
| `services` | `name`, `slug` (unique), `department`, `is_active` |
| `workflows` | `title`, `status`, `feature_doc_text`, `repo_url`, `branch`, `requirement_summary` (JSONB), `technical_design` (JSONB), `tasks` (JSONB), `pr_url` |
| `agent_runs` | `workflow_id` (FK), `agent_name`, `status`, `input_data`/`output_data` (JSONB), `model_used`, `tokens_used`, `duration_ms` |
| `service_integrations` | `service_id` (FK), `integration_type`, `provider`, `config` (JSONB) |

## Setup

### Prerequisites

- Python 3.12+
- PostgreSQL
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

```bash
# Install dependencies
uv sync

# Copy and configure environment variables
cp .env.example .env
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string (aliases: `POSTGRES_URL`, `POSTGRESQL_URL`) | `postgresql+psycopg://postgres:postgres@localhost:5432/feature_delivery` |
| `ENVIRONMENT` | `development` / `production` | `development` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `GITHUB_TOKEN` | Fallback GitHub PAT for repo operations | — |
| `REPO_WORKSPACE_DIR` | Local directory for cloned repos | `/tmp/fde-workspaces` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OpenTelemetry collector endpoint | — |
| `OTEL_EXPORTER_OTLP_HEADERS` | OTel exporter headers (`Key=Value,...`) | — |
| `SENTRY_DSN` | Sentry error tracking DSN | — |

### Railway

1. Add a **PostgreSQL** database in the same Railway project.
2. On the **API service** → **Variables**: set `DATABASE_URL` via **variable reference** to the Postgres service’s `DATABASE_URL`, or link the services so Railway injects `PGHOST` / `PGUSER` / `PGPASSWORD` / `PGDATABASE`. Avoid an empty `DATABASE_URL` placeholder.
3. Use a start command that runs migrations then the app (see `railway.toml` and `Procfile`). The backend normalizes `postgres://` URLs and can build a URL from split `PG*` vars when Postgres is linked.

### Database

```bash
# Run migrations
uv run alembic upgrade head
```

### Running

```bash
# Development (with hot reload)
uv run uvicorn app.main:app --reload --port 8000

# Production (as in Procfile)
uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

API docs are available at `http://localhost:8000/docs` once the server is running.

## Testing

```bash
uv run pytest
uv run pytest --cov       # with coverage
```

Tests use async fixtures with a mocked database and LLM client. See `tests/conftest.py` for shared setup.

## Workflow Status FSM

```
draft → parsing → awaiting_clarification → parsing → designing → reviewing
                                                          ↕ (rework loop)
reviewing → ticketing → implementing → code_reviewing → pr_created → completed
                             ↕ (fix loop)
Any state → failed → draft (retry)
```
