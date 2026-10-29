# Task Management API

Backend REST API for managing tasks, task comments, deadlines, and aggregate statistics.
Built with Python 3.13, FastAPI, SQLAlchemy Async, PostgreSQL, Alembic, Pydantic, and a
separate periodic deadline worker.

The approved requirements and resolved decisions are documented in
[`TECHNICAL_SPECIFICATION.md`](TECHNICAL_SPECIFICATION.md).

## Contents

- [Requirements](#requirements)
- [Quick start with Docker Compose](#quick-start-with-docker-compose)
- [Local development without Docker](#local-development-without-docker)
- [Configuration](#configuration)
- [Database migrations](#database-migrations)
- [Roles and admin provisioning](#roles-and-admin-provisioning)
- [API overview](#api-overview)
- [Request and response examples](#request-and-response-examples)
- [Task list query parameters](#task-list-query-parameters)
- [Task rules](#task-rules)
- [Comments](#comments)
- [Overdue tasks and statistics](#overdue-tasks-and-statistics)
- [Deadline worker](#deadline-worker)
- [Error responses](#error-responses)
- [Tests and quality checks](#tests-and-quality-checks)
- [CI, commit messages, and hooks](#ci-commit-messages-and-hooks)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)

## Requirements

- Python 3.13
- [`uv`](https://docs.astral.sh/uv/) 0.13+
- Docker and Docker Compose (for the full local stack)
- PostgreSQL 16 (when running without Docker)

## Quick start with Docker Compose

1. Create the environment file and replace the example secrets:

   ```bash
   cp .env.example .env
   ```

   At minimum, replace `JWT_SECRET_KEY` and `POSTGRES_PASSWORD` in `.env`. The JWT secret
   must be at least 32 characters; the application refuses to start with a shorter value.

2. Build and start the stack:

   ```bash
   docker compose up --build
   ```

   The `migrate` service runs `alembic upgrade head` after PostgreSQL reports healthy. The
   API and deadline worker start only after migrations complete successfully. A failed
   migration prevents both from starting.

3. Open the API:

   - Swagger UI: <http://localhost:8000/docs>
   - ReDoc: <http://localhost:8000/redoc>
   - OpenAPI schema: <http://localhost:8000/openapi.json>
   - Health check: <http://localhost:8000/api/v1/health>

4. Follow the worker logs when needed:

   ```bash
   docker compose logs -f worker
   ```

5. Stop the stack. Add `-v` only when you intentionally want to delete the database volume:

   ```bash
   docker compose down
   docker compose down -v
   ```

## Local development without Docker

Start a local PostgreSQL instance and create a database/user that matches your
`DATABASE_URL`, then:

```bash
uv sync
cp .env.example .env
# For a database on the host, change the host in DATABASE_URL, for example:
# DATABASE_URL=postgresql+asyncpg://task_user:change-me@localhost:5432/task_management
uv run alembic upgrade head
uv run uvicorn task_management_api.main:app --reload
```

Run the deadline worker in a second terminal:

```bash
uv run python -m task_management_api.worker
```

The API reads settings from environment variables and `.env`. The test suite does not need
a running PostgreSQL instance; it uses SQLite (see
[Tests and quality checks](#tests-and-quality-checks)).

## Configuration

All settings are read from environment variables or `.env`. Variable names are
case-insensitive.

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `Task Management API` | OpenAPI title |
| `APP_ENV` | `development` | Application environment label |
| `DATABASE_URL` | local PostgreSQL URL | SQLAlchemy async database URL |
| `JWT_SECRET_KEY` | development placeholder | JWT signing secret; minimum 32 characters |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access-token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh-token lifetime |
| `WORKER_INTERVAL_SECONDS` | `300` | Deadline-worker check interval |
| `TIMEZONE` | `Europe/Kyiv` | Timezone used for deadline boundaries |
| `DOCS_ENABLED` | `true` | Enables `/docs`, `/redoc`, and `/openapi.json` |
| `LOG_LEVEL` | `INFO` | Application and worker log level |
| `PAGE_SIZE_DEFAULT` | `20` | Default `page_size` |
| `PAGE_SIZE_MAX` | `100` | Maximum accepted `page_size` |

`PAGE_SIZE_DEFAULT` must not exceed `PAGE_SIZE_MAX`. `TIMEZONE` must be a valid IANA zone.
The `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` variables in `.env.example` are
used by Docker Compose to initialize PostgreSQL; the application itself uses
`DATABASE_URL`.

Never commit a real `.env` file or real credentials.

## Database migrations

Alembic is configured in `alembic.ini` and reads `DATABASE_URL` through the application
settings.

```bash
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe change"
uv run alembic downgrade -1
```

In Docker Compose, migrations are applied by the `migrate` service before the API and
worker start. Do not run the API or worker against an unmigrated database.

## Roles and admin provisioning

Registration is public and always assigns the `user` role. Clients cannot submit a role,
and server-managed fields are rejected by request validation.

- A `user` can view all non-deleted tasks and create tasks. The user can edit, delete,
  assign, and change the status only of tasks they created.
- An `admin` can manage every task.
- Comments are readable and creatable by any authenticated user who can access the task.
  Only the comment author can edit or delete a comment, including when the author is an
  admin.

There is no admin-registration endpoint. Provision the first admin directly in PostgreSQL:

```sql
UPDATE users SET role = 'admin' WHERE username = 'alice';
```

The role is loaded from the database on each authenticated request, so no restart is
required. Use this operation deliberately; it grants full task-management permissions.

## API overview

All endpoints are under `/api/v1`. Except for registration, login, refresh, and health,
every endpoint requires `Authorization: Bearer <access_token>`.

| Method | Path | Purpose | Authorization |
|---|---|---|---|
| `POST` | `/auth/register` | Register a user | Public |
| `POST` | `/auth/login` | Obtain access and refresh tokens | Public |
| `POST` | `/auth/refresh` | Rotate a refresh token | Public (valid refresh token) |
| `POST` | `/auth/logout` | Revoke a refresh token | Authenticated |
| `GET` | `/health` | Health check | Public |
| `GET` | `/tasks` | List, search, filter, sort, paginate tasks | Authenticated |
| `POST` | `/tasks` | Create a task | Authenticated |
| `GET` | `/tasks/overdue` | List overdue tasks | Authenticated |
| `GET` | `/tasks/statistics` | Global task statistics | Authenticated |
| `GET` | `/tasks/{task_id}` | Get one task | Authenticated |
| `PATCH` | `/tasks/{task_id}` | Edit task fields | Task creator or admin |
| `PATCH` | `/tasks/{task_id}/status` | Change task status | Task creator or admin |
| `DELETE` | `/tasks/{task_id}` | Soft-delete a task | Task creator or admin |
| `GET` | `/tasks/{task_id}/comments` | List comments on a task | Authenticated |
| `POST` | `/tasks/{task_id}/comments` | Create a comment | Authenticated |
| `PATCH` | `/comments/{comment_id}` | Edit a comment | Comment author |
| `DELETE` | `/comments/{comment_id}` | Delete a comment | Comment author |

### Response shapes

Task:

```json
{
  "id": "5f0c6f1e-6f4f-4a0e-9d6e-3f2a1b7c8d90",
  "title": "Prepare release",
  "description": "Release notes and checks",
  "status": "Backlog",
  "priority": "Medium",
  "assignee_id": null,
  "created_by_id": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
  "due_date": "2026-11-15",
  "created_at": "2026-10-29T12:00:00Z",
  "updated_at": "2026-10-29T12:00:00Z"
}
```

Task page:

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "pages": 0
}
```

Comment:

```json
{
  "id": "9a8b7c6d-5e4f-4321-8765-0fedcba98765",
  "task_id": "5f0c6f1e-6f4f-4a0e-9d6e-3f2a1b7c8d90",
  "author_id": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
  "body": "Looks good",
  "created_at": "2026-10-29T12:05:00Z",
  "updated_at": "2026-10-29T12:05:00Z"
}
```

Timestamps are ISO 8601 UTC values ending in `Z`. `due_date` is a calendar date in
`YYYY-MM-DD` format and is not an instant in time.

## Request and response examples

Register and log in:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "password123"}'

TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "password123"}' \
  | jq -r .access_token)
```

Create a task:

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Prepare release",
    "description": "Release notes and checks",
    "priority": "High",
    "due_date": "2026-11-15"
  }'
```

List tasks:

```bash
curl "http://localhost:8000/api/v1/tasks?status=Backlog&priority=High&page=1&page_size=20" \
  -H "Authorization: Bearer $TOKEN"
```

Get one task, update it, and move it through the workflow:

```bash
TASK_ID="<task-id>"

curl http://localhost:8000/api/v1/tasks/$TASK_ID \
  -H "Authorization: Bearer $TOKEN"

curl -X PATCH http://localhost:8000/api/v1/tasks/$TASK_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "Prepare release v1.1", "due_date": null}'

curl -X PATCH http://localhost:8000/api/v1/tasks/$TASK_ID/status \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "In Progress"}'
```

A task must have an assignee before it can move to `Done`:

```bash
curl -X PATCH http://localhost:8000/api/v1/tasks/$TASK_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"assignee_id": "<user-id>"}'

curl -X PATCH http://localhost:8000/api/v1/tasks/$TASK_ID/status \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "Review"}'

curl -X PATCH http://localhost:8000/api/v1/tasks/$TASK_ID/status \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "Done"}'
```

Add and edit a comment:

```bash
curl -X POST http://localhost:8000/api/v1/tasks/$TASK_ID/comments \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"body": "Release notes are ready"}'

COMMENT_ID="<comment-id>"

curl -X PATCH http://localhost:8000/api/v1/comments/$COMMENT_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"body": "Release notes are ready for review"}'
```

Refresh and log out:

```bash
REFRESH_TOKEN="<refresh-token>"

curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d "{\"refresh_token\": \"$REFRESH_TOKEN\"}"

curl -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"refresh_token\": \"$REFRESH_TOKEN\"}"
```

Refresh tokens are single-use. A successful refresh returns a new refresh token and
revokes the previous one; replaying a revoked token returns `401`.

## Task list query parameters

`GET /api/v1/tasks` accepts:

| Parameter | Meaning |
|---|---|
| `q` | Case-insensitive substring search over title and description (maximum 200 characters) |
| `status` | Repeatable status filter, for example `?status=Backlog&status=Review` |
| `priority` | Repeatable priority filter |
| `assignee_id` | UUID filter |
| `due_from` | Inclusive lower bound for `due_date` |
| `due_to` | Inclusive upper bound for `due_date` |
| `sort_by` | `created_at`, `due_date`, or `priority` |
| `sort_order` | `asc` (default) or `desc` |
| `page` | Page number, starting at 1 (default 1) |
| `page_size` | Page size (default 20, maximum 100) |

Filters combine with AND. Search wildcards in `q` are escaped and treated literally.

Default ordering is priority `High` → `Medium` → `Low`, then nearest `due_date` with null
deadlines last, then `id ASC`. A custom `sort_by` replaces that ordering, keeps null
deadlines last, and still appends `id ASC` as a deterministic tie-breaker. Priority
ascending means `High` → `Medium` → `Low`.

Soft-deleted tasks are excluded from list, detail, overdue, comments, and statistics.

## Task rules

- New tasks always start in `Backlog`; the initial status cannot be supplied by a client.
- Title is required, 1–200 characters, and cannot be blank. Description is optional, up to
  10,000 characters.
- Priority defaults to `Medium`.
- `due_date` may be omitted or cleared. It must not be earlier than today in the configured
  timezone; today's date is valid.
- `created_by_id`, timestamps, identifiers, and status are server-managed and rejected in
  create/update payloads.
- A user may manage only tasks they created; an admin may manage all tasks.
- Tasks in `Done` or `Cancelled` cannot be edited.
- The assignee cannot be changed once a task is in `Review` or `Done`.
- Soft deletion is allowed only in `Backlog`, `Done`, and `Cancelled`; it is rejected in
  `In Progress` and `Review`.
- Each assignee may have at most 10 active tasks (`Backlog`, `In Progress`, `Review`).
  The limit is checked on creation and assignment, and the operation is rejected without
  partially persisting the change.

User-initiated status transitions:

| Current status | Allowed target statuses |
|---|---|
| `Backlog` | `In Progress`, `Cancelled` |
| `In Progress` | `Review`, `Cancelled` |
| `Review` | `Done` |
| `Done` | None |
| `Cancelled` | None |

`Review → Done` requires an assignee. If a deadline is set, it must not be earlier than
today. A task may move to `Done` without a deadline when it has an assignee. Backward
transitions and every transition not listed above are rejected.

The only system-initiated exception is the deadline worker, which may move an overdue task
from `Backlog`, `In Progress`, or `Review` to `Cancelled`.

## Comments

- Any authenticated user can list and create comments on a non-deleted task.
- Comments are allowed on `Done` and `Cancelled` tasks.
- The body is required, 1–2000 characters, and cannot be blank.
- Only the comment author can edit or delete a comment. Admins do not get an override.
- Soft-deleted tasks and their comments return `404`.

## Overdue tasks and statistics

`GET /api/v1/tasks/overdue` returns tasks that have a `due_date` earlier than today in the
configured timezone and a status of `Backlog`, `In Progress`, or `Review`. A task due today
is not overdue. The endpoint is global, paginated, and excludes soft-deleted tasks.

`GET /api/v1/tasks/statistics` returns:

```json
{
  "total": 4,
  "by_status": {
    "Backlog": 1,
    "In Progress": 1,
    "Review": 0,
    "Done": 1,
    "Cancelled": 1
  },
  "by_priority": {
    "High": 1,
    "Medium": 2,
    "Low": 1
  },
  "overdue": 0,
  "active": 2
}
```

Every status and priority category is present, including zero counts. `active` counts
`Backlog`, `In Progress`, and `Review`. Soft-deleted tasks are excluded from every field.

## Deadline worker

The worker runs in a separate process/container and performs a startup catch-up check,
then repeats every `WORKER_INTERVAL_SECONDS` (default 300 seconds).

On each check it atomically updates eligible tasks to `Cancelled` and updates `updated_at`.
Eligibility is re-checked at write time, so a task that becomes `Done` concurrently is not
overwritten. The worker does not create comments, notifications, or history records.

A failed check is logged without sensitive details or a stack trace, and the worker
continues with the next scheduled check. It logs startup, check start/end, the number of
cancelled tasks, and recoverable errors.

Run it locally with:

```bash
uv run python -m task_management_api.worker
```

In Docker Compose it starts as the `worker` service after migrations complete.

## Error responses

Application errors use FastAPI's standard shape:

```json
{"detail": "Task not found"}
```

Request validation errors (`422`) use FastAPI's validation detail list, with submitted
input values and validation context removed so credentials and tokens are never echoed.
Unexpected failures return `500` with a generic message and never expose internal details,
stack traces, or raw SQL.

| Status | Typical causes |
|---|---|
| `401` | Missing/invalid/expired access token, invalid refresh token, replayed or revoked refresh token, wrong credentials |
| `403` | Editing/deleting/transitioning another user's task, editing another user's comment |
| `404` | Missing or soft-deleted task or comment |
| `409` | Duplicate username, invalid status transition, editing a terminal task, changing an assignee in `Review`, missing `Done` prerequisites, active-task limit, prohibited deletion |
| `422` | Invalid enum/UUID, field length violation, past `due_date`, unknown assignee, `page_size` above the configured maximum |
| `500` | Unexpected internal failure |

## Tests and quality checks

The complete test suite uses SQLite through `aiosqlite`; production uses PostgreSQL. SQLite
does not fully reproduce PostgreSQL locking, type, concurrency, and constraint behavior, so
the tests do not prove every PostgreSQL-specific guarantee. PostgreSQL race protections are
implemented with row locks and conditional writes and are documented in the code and
specification.

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Run all three before submitting a change. The test suite covers authentication and token
rotation, task CRUD and permissions, the full status-transition matrix, soft deletion, the
active-assignee limit, comments, list filtering/sorting/pagination, overdue tasks,
statistics, the deadline worker, migrations, configuration, and error handling.

## CI, commit messages, and hooks

GitHub Actions runs on pushes to `develop` and pull requests targeting `develop`. It
validates commit messages and the pull-request title, runs Ruff lint and format checks, and
runs Pytest.

Commit messages follow Conventional Commits, for example:

```text
feat(tasks): add overdue filter
fix(auth): reject replayed refresh token
docs: document worker operation
```

Enable the local commit-message hook once per clone:

```bash
git config core.hooksPath .githooks
```

The hook validates the message locally; CI validates commits and pull-request titles
independently. Merge commits are exempt from the Conventional Commit subject check because
they do not represent a change of their own. `.gitattributes` keeps hook scripts on LF line
endings.

## Project layout

```text
src/task_management_api/
  api/          HTTP routes, dependencies, pagination, query parameters
  core/         configuration, clock, security, errors, time helpers
  db/           SQLAlchemy base and async session management
  models/       SQLAlchemy models
  schemas/      Pydantic request/response schemas
  services/     business rules and persistence orchestration
  workers/      periodic deadline worker
tests/          Pytest suite (SQLite)
migrations/     Alembic environment and revisions
scripts/        commit-message validation
.githooks/      local Git hooks
```

## Troubleshooting

**The application fails to start with a settings validation error.**
Check `JWT_SECRET_KEY` (at least 32 characters), `TIMEZONE` (valid IANA zone), and that
`PAGE_SIZE_DEFAULT` is not greater than `PAGE_SIZE_MAX`.

**Docker Compose reports that `.env` is missing.**
Run `cp .env.example .env` and set real values. Compose reads the same file for PostgreSQL
credentials and application settings.

**The API or worker does not start in Compose.**
Check `docker compose logs migrate` first. Both services wait for the migration service to
complete successfully. Then check `docker compose ps` and the `db` health status.

**Requests return `401` after about 15 minutes.**
Access tokens expire after 15 minutes. Use the refresh token to obtain a new pair; refresh
tokens expire after 7 days and are rotated on every use.

**The worker does not cancel a task that looks overdue.**
Only tasks with a due date strictly earlier than today in `TIMEZONE` are eligible. Tasks due
today, tasks without a deadline, soft-deleted tasks, and tasks already in `Done` or
`Cancelled` are left unchanged. A newly cancelled task also requires the next check cycle
unless the worker has just started.

**A task cannot move to `Done`.**
The task needs an assignee. If it has a deadline, the deadline must not be earlier than
today. The task must also be in `Review`; direct `Backlog → Done` and `In Progress → Done`
are not allowed.

**A task cannot be deleted.**
Deletion is prohibited in `In Progress` and `Review`. Move the task to an allowed status
first; terminal tasks can be soft-deleted.

**A user cannot edit a task they can see.**
Visibility is global, but management is ownership-based. Only the creator or an admin can
edit, delete, assign, or change the status.

**Tests pass locally but PostgreSQL behavior differs.**
The suite uses SQLite by design. Verify PostgreSQL-specific behavior, especially concurrent
assignment and worker/API races, against a real PostgreSQL instance before relying on it in
production.
