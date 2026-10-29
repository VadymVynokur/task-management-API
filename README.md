# Task Management API

Backend REST API for managing tasks, task comments, deadlines, and aggregate statistics.
Built with Python 3.13, FastAPI, SQLAlchemy Async, PostgreSQL, Alembic, Pydantic, and a
separate periodic deadline worker.

The approved requirements and resolved decisions are documented in
[`TECHNICAL_SPECIFICATION.md`](TECHNICAL_SPECIFICATION.md).

## Requirements

- Python 3.13
- [`uv`](https://docs.astral.sh/uv/) 0.13+
- Docker and Docker Compose (for the full local stack)

## Quick start with Docker Compose

1. Copy the example environment file and set a real JWT secret:

   ```bash
   cp .env.example .env
   ```

   At minimum, replace `JWT_SECRET_KEY` and `POSTGRES_PASSWORD` in `.env`.

2. Build and start the stack:

   ```bash
   docker compose up --build
   ```

   The `migrate` service runs `alembic upgrade head` after PostgreSQL is healthy. The API
   and deadline worker start only after migrations complete successfully.

3. Open the API documentation:

   - Swagger UI: <http://localhost:8000/docs>
   - ReDoc: <http://localhost:8000/redoc>
   - Health check: <http://localhost:8000/api/v1/health>

## Local development without Docker

```bash
uv sync
cp .env.example .env
# Point DATABASE_URL at a local PostgreSQL instance, for example:
# DATABASE_URL=postgresql+asyncpg://task_user:task_password@localhost:5432/task_management
uv run alembic upgrade head
uv run uvicorn task_management_api.main:app --reload
```

Run the deadline worker in a second terminal:

```bash
uv run python -m task_management_api.worker
```

## Configuration

All settings are read from environment variables or `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | Application environment label |
| `DOCS_ENABLED` | `true` | Enables `/docs`, `/redoc`, and `/openapi.json` |
| `LOG_LEVEL` | `INFO` | Application and worker log level |
| `DATABASE_URL` | local PostgreSQL URL | SQLAlchemy async database URL |
| `JWT_SECRET_KEY` | development placeholder | JWT signing secret; must be replaced outside local use |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access-token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh-token lifetime |
| `WORKER_INTERVAL_SECONDS` | `300` | Deadline-worker check interval |
| `TIMEZONE` | `Europe/Kyiv` | Timezone used for deadline boundaries |
| `PAGE_SIZE_DEFAULT` | `20` | Default `page_size` |
| `PAGE_SIZE_MAX` | `100` | Maximum accepted `page_size` |

Never commit a real `.env` file or real credentials.

## Database migrations

Alembic is configured in `alembic.ini` and reads `DATABASE_URL` through the application
settings.

```bash
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe change"
```

In Docker Compose, migrations are applied by the `migrate` service before the API and
worker start. A failed migration prevents both from starting.

## Tests and quality checks

The complete test suite uses SQLite (via `aiosqlite`); production uses PostgreSQL. SQLite
does not fully reproduce PostgreSQL locking, type, and concurrency behavior, so tests do
not prove every PostgreSQL-specific guarantee. PostgreSQL-specific race protections are
implemented with row locks and conditional writes and are documented where relevant.

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Commit messages and hooks

Commit messages follow Conventional Commits. Enable the local hook once per clone:

```bash
git config core.hooksPath .githooks
```

The hook validates the message locally; GitHub Actions validates commits and pull-request
titles independently.

## Project layout

```text
src/task_management_api/
  api/          HTTP routes and dependencies
  core/         configuration, clock, security, errors
  db/           SQLAlchemy base and async session management
  models/       SQLAlchemy models
  schemas/      Pydantic request/response schemas
  services/     business rules and persistence orchestration
  workers/      periodic deadline worker
tests/          Pytest suite (SQLite)
migrations/     Alembic environment and revisions
```
