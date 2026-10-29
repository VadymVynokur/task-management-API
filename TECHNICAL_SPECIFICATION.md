# Task Management API — Technical Specification

- **Document status:** Approved for implementation; all blocking decisions were resolved on 2026-10-29.
- **Language:** English
- **Last updated:** 2026-10-29
- **Primary audience:** Backend developers, code agents, reviewers, and QA engineers
- **Project type:** REST API

## 1. Purpose and scope

The system is a backend REST API for managing tasks. Authenticated users can create and manage tasks according to role- and ownership-based authorization, assign task executors, change task statuses through a dedicated operation, comment on tasks, search/filter/sort/paginate task collections, inspect overdue tasks, and retrieve aggregate statistics.

The system also contains a separate periodic worker that automatically moves eligible overdue tasks to `Cancelled`.

### 1.1 In scope

- User registration and username/password authentication.
- JWT access and refresh tokens, including refresh-token rotation.
- Role-based authorization, with the exact role names and permission matrix still to be approved.
- Task CRUD with soft deletion.
- Task status-transition validation.
- Task comments.
- Task search, filtering, sorting, and pagination.
- Overdue-task and task-statistics endpoints.
- Periodic overdue-task cancellation and startup catch-up.
- PostgreSQL persistence, SQLAlchemy Async, Alembic migrations, and Pydantic validation.
- Docker Compose-based local execution.
- Pytest tests and a GitHub Actions quality pipeline.
- Test-driven development (TDD).

### 1.2 Out of scope unless explicitly approved later

- Frontend or user interface.
- Email verification and password-reset workflows.
- Email, push, or in-app notifications.
- Audit-history/event-log functionality beyond updating the task's `updated_at` timestamp.
- A message broker or distributed task queue.
- Performance service-level objectives or capacity guarantees; no numeric targets have been provided.
- A production deployment platform beyond the agreed Docker Compose execution environment.

## 2. Status of decisions and handling ambiguity

This document distinguishes approved requirements from unresolved decisions. An unresolved item must not be silently resolved by an implementation agent.

- **Approved:** explicitly selected by the requester or accepted in conversation.
- **Proposed implementation detail:** a reasonable implementation approach, but not an additional business requirement unless confirmed.
- **TBD / blocking:** a decision that remains open. Record the final decision here before implementing dependent behavior.

### 2.1 Resolved decisions

All blocking decisions were approved on 2026-10-29. Implementation must follow the resolutions below.

| ID | Decision | Approved resolution |
|---|---|---|
| DEC-01 | Exact role names and permission matrix | Roles are `user` and `admin`; registration assigns `user`. A `user` may view all non-deleted tasks and create tasks, but may edit, soft-delete, assign, or change status only for tasks they created. An `admin` may manage all tasks. All authenticated users may read and create comments on accessible tasks; only the comment author may edit or delete a comment, including when the author is an `admin`. |
| DEC-02 | Task and user identifier types | UUID (`uuid4`) identifiers for users, tasks, and comments. |
| DEC-03 | Task title and description constraints | Title is required, 1–200 characters. Description is optional/nullable, up to 10,000 characters. |
| DEC-04 | Completion when no deadline is set | A task may transition to `Done` without a deadline when it has an assignee. |
| DEC-05 | Soft-delete visibility and statistics | Soft-deleted tasks are hidden from detail, list, overdue, and statistics results and are inaccessible for comments (404). Statistics exclude them consistently. |
| DEC-06 | JWT lifetimes and logout/revocation | Access tokens live 15 minutes; refresh tokens live 7 days. Refresh tokens are stored hashed in the database, rotated on every refresh, and the previous token is revoked. Reuse of a revoked/replayed refresh token is rejected with 401. Logout revokes the supplied refresh token. |
| DEC-07 | Pagination defaults and maximum | `page` defaults to 1; `page_size` defaults to 20 and is capped at 100. |
| DEC-08 | Deadline-filter boundary semantics | `due_from` and `due_to` are both inclusive. |
| DEC-09 | Custom sort behavior and sort-direction semantics | A single `sort_by` (`created_at`, `due_date`, or `priority`) and `sort_order` (`asc` or `desc`). Priority ascending means `High` → `Medium` → `Low`. Custom sorting replaces the default ordering. Null deadlines are always last. The final tie-breaker is `id ASC`. Default ordering is priority `High` → `Medium` → `Low`, then nearest `due_date` (null last), then `id ASC`. |
| DEC-10 | CI triggers and merge strategy | CI runs on pushes to `develop` and on pull requests targeting `develop`. Changes merge into `develop` using squash merge. |
| DEC-11 | Alembic orchestration in Compose | A dedicated `migrate` Compose service runs `alembic upgrade head` after PostgreSQL is healthy. API and worker start only after that service completes successfully. |
| DEC-12 | HTTP status codes for individual domain errors | 401 for authentication failures; 403 for insufficient permissions; 404 for missing or soft-deleted resources; 409 for business conflicts (duplicate username, invalid transition, terminal-task edit, assignee change, `Done` prerequisites, active-task limit, prohibited deletion); 422 for request/field validation (invalid enum, UUID, lengths, past deadline); 500 for unexpected failures without internal details. |
| DEC-13 | Soft-delete representation | A nullable `deleted_at` timestamp. Soft deletion also updates `updated_at`. |
| DEC-14 | Comment behavior on terminal/deleted tasks | Comments are allowed on `Done` and `Cancelled` tasks. Soft-deleted tasks and their comments are inaccessible (404). Comment body is 1–2000 characters; only the author may edit or delete. |
| DEC-15 | Stable sorting tie-breaker | `id ASC` is appended as the final deterministic tie-breaker. |

Additional approved implementation details:

- New tasks always start in `Backlog`; clients cannot set the initial status.
- Usernames are 3–50 characters matching `[A-Za-z0-9_-]`.
- Passwords are 8–128 characters.

## 3. Technology requirements

### 3.1 Required stack

| Concern | Required technology |
|---|---|
| HTTP API | FastAPI |
| Persistence | SQLAlchemy Async |
| Production database | PostgreSQL |
| Schema migration | Alembic |
| Request/response validation | Pydantic |
| Runtime and dependency management | Python 3.13 and `uv` |
| Containers | Docker Compose |
| Tests | Pytest |
| Code linting and formatting | Ruff |
| CI | GitHub Actions |

### 3.2 Test database

The selected test database is SQLite for all tests. Use an async-compatible SQLite driver where needed by the chosen SQLAlchemy setup.

**Known limitation:** SQLite does not fully reproduce PostgreSQL behavior, including some type, query, locking, concurrency, and constraint semantics. Tests must be written to the selected SQLite setup, but the specification must not claim that SQLite-based tests prove every PostgreSQL-specific behavior. Keep SQLAlchemy usage portable where possible and explicitly identify PostgreSQL-specific risks. A PostgreSQL test service was not selected.

### 3.3 Required runtime components

The Docker Compose environment must provide:

1. **API service** — serves FastAPI endpoints.
2. **PostgreSQL service** — stores application data.
3. **Deadline worker service** — periodically finds and cancels eligible overdue tasks.
4. **Migration execution step/service** — applies Alembic migrations before the API and worker start using the database schema.

The migration orchestration mechanism is defined in DEC-11: a dedicated Compose `migrate` service runs Alembic before API and worker startup. API and worker startup must not race ahead of a failed or incomplete migration. Worker and API must use the same configured database and compatible application code.

## 4. Domain model

Names below describe the logical domain. Exact identifier types, SQL field types, and some storage details remain subject to the decisions in Section 2.1.

### 4.1 User

A user record must support:

- A unique username used for login.
- A securely hashed password; plaintext passwords must never be stored.
- One or more role assignments according to the approved role model.
- Creation timestamp, if retained by the final schema decision.

Email is not required by the approved authentication flow. Email verification and password reset are out of scope.

### 4.2 Task

Each task must represent at least the following fields:

| Field | Requirement |
|---|---|
| `id` | Unique UUID identifier. |
| `title` | Required task title, 1–200 characters. |
| `description` | Optional/nullable task description up to 10,000 characters. |
| `status` | One of `Backlog`, `In Progress`, `Review`, `Done`, `Cancelled`. New tasks are expected to begin in `Backlog`; confirm if this must be a hard rule before implementation. |
| `priority` | `High`, `Medium`, or `Low`; default is `Medium`. |
| `assignee_id` | Reference to the assigned executor; may be empty unless the approved `Done` rule requires an assignee. |
| `created_by_id` | Reference to the user who created the task; assigned by the server from the authenticated principal, never trusted from an arbitrary client-supplied author field. |
| `due_date` | Optional calendar date without a time component. |
| `created_at` | Server-generated creation timestamp. |
| `updated_at` | Server-maintained last-update timestamp. Must be updated on task updates and automatic status changes. |
| soft-delete marker | A nullable `deleted_at` timestamp that makes deletion reversible at the storage level. |

The task response must expose dates/timestamps using a consistent documented serialization format. `due_date` is a calendar date and must not be treated as an instant in time. `created_at` and `updated_at` are timestamps.

### 4.3 Comment

A comment must include:

- Unique UUID identifier.
- Reference to the task.
- Reference to the user who created it, derived from authentication.
- Comment body, 1–2000 characters.
- Creation timestamp.
- Updated timestamp for auditable edits.

All authenticated users who have access to the task may read and create comments. Users may edit and delete their own comments. Because authenticated users can view all non-deleted tasks under the approved visibility rule, “has access to the task” means the task is not soft-deleted. Comments are allowed on `Done` and `Cancelled` tasks; soft-deleted tasks and their comments are inaccessible (404).

### 4.4 Task statuses

The only approved statuses are:

- `Backlog`
- `In Progress`
- `Review`
- `Done`
- `Cancelled`

`Todo` in the original description is a naming error and must not be implemented as a separate status. The corresponding active status is `Backlog`.

### 4.5 Priorities

The only approved priorities are `High`, `Medium`, and `Low`. The default is `Medium`. For default list ordering, the required order is `High`, then `Medium`, then `Low`.

## 5. Functional requirements

### FR-AUTH — Registration and authentication

- **FR-AUTH-001:** The API must provide public user registration.
- **FR-AUTH-002:** Authentication must use username and password.
- **FR-AUTH-003:** Passwords must be stored using a suitable password-hashing algorithm. Plaintext and reversible plaintext-equivalent storage are prohibited.
- **FR-AUTH-004:** Successful login must issue a JWT access token and a refresh token.
- **FR-AUTH-005:** Refresh-token use must rotate the refresh token. Token lifetime, revocation storage, replay handling, and logout behavior must be specified under DEC-06 before implementation.
- **FR-AUTH-006:** Protected endpoints must reject requests without valid authentication, except public registration and login/refresh routes as defined by the final route contract.
- **FR-AUTH-007:** Password reset and email verification must not be implemented unless separately approved.
- **FR-AUTH-008:** Registration assigns the `user` role. The role is never taken from client input.

### FR-USER — Roles and authorization

- **FR-USER-001:** The application must support multiple user roles.
- **FR-USER-002:** Every protected operation must enforce a server-side authorization decision. Hiding operations in documentation or clients is not authorization.
- **FR-USER-003:** Any authenticated user may list and view tasks across the system under the approved global visibility rule.
- **FR-USER-004:** A user may create, edit, delete, assign, or change the status of a task only when permitted by the final role/ownership matrix.
- **FR-USER-005:** A user may create comments on tasks they can access and may edit or delete only their own comments.
- **FR-USER-006:** The approved roles are `user` and `admin`. A `user` may manage only tasks they created; an `admin` may manage all tasks. Elevated permissions are never granted implicitly by client input.

### FR-TASK — Task creation and retrieval

- **FR-TASK-001:** An authorized authenticated user must be able to create a task.
- **FR-TASK-002:** Task creation must accept the approved task fields and must set `created_by_id`, `created_at`, and `updated_at` on the server.
- **FR-TASK-003:** New tasks always start in `Backlog`; clients cannot set the initial status.
- **FR-TASK-004:** If priority is omitted, it must default to `Medium`.
- **FR-TASK-005:** The deadline is optional.
- **FR-TASK-006:** The deadline may not be earlier than the current calendar date in `Europe/Kyiv` when creating or editing a task. A deadline equal to today's date is valid.
- **FR-TASK-007:** Task creation and editing must validate references, enum values, and field constraints. Title is 1–200 characters and description is at most 10,000 characters.
- **FR-TASK-008:** An authorized user must be able to retrieve an individual task, subject to the final soft-delete visibility policy (DEC-05/DEC-13).

### FR-TASK — Task update

- **FR-TASK-009:** An authorized user must be able to update task fields through the task update endpoint.
- **FR-TASK-010:** `created_by_id`, `created_at`, and other server-managed fields must not be writable by clients.
- **FR-TASK-011:** A task in `Done` or `Cancelled` must not be editable. The delete endpoint is governed separately by FR-TASK-017.
- **FR-TASK-012:** Once a task reaches `Review` or `Done`, its assignee must not be changed. This restriction applies regardless of whether the request is a full update or a partial update.
- **FR-TASK-013:** A task due date may be omitted or set to a date on or after the current date, but not an earlier date. If clearing an existing due date is supported, the request schema must explicitly permit `null`.
- **FR-TASK-014:** When the assignee is set or changed, the active-task limit must be checked for the target assignee as described in FR-LIMIT.

### FR-STATUS — Separate status-transition operation

- **FR-STATUS-001:** Status changes must be performed through a dedicated endpoint, not by ordinary task update.
- **FR-STATUS-002:** The API must accept a target status and validate the transition against the approved transition matrix.
- **FR-STATUS-003:** The only user-initiated transitions currently approved are:

  | Current status | Allowed target status |
  |---|---|
  | `Backlog` | `In Progress`, `Cancelled` |
  | `In Progress` | `Review`, `Cancelled` |
  | `Review` | `Done` |
  | `Done` | None |
  | `Cancelled` | None |

- **FR-STATUS-004:** Any transition not explicitly listed above must fail. In particular, backward transitions are forbidden.
- **FR-STATUS-005:** A task may transition to `Done` only if it has an assignee and its deadline has not passed. Since the deadline is a calendar date, the due date remains valid through the end of that date in `Europe/Kyiv`.
- **FR-STATUS-006:** A task may transition to `Done` without a deadline when it has an assignee.
- **FR-STATUS-007:** The assignee must not be changed after a task enters `Review` or `Done`.
- **FR-STATUS-008:** Status change must update `updated_at`.
- **FR-STATUS-009:** The periodic worker has one system-only exception: it may transition an overdue task in `Backlog`, `In Progress`, or `Review` to `Cancelled`. This does not add `Review -> Cancelled` to the set of user-initiated transitions.
- **FR-STATUS-010:** Concurrent status updates must not allow the worker to overwrite a successfully completed task with `Cancelled`. The worker must use an atomic/conditional update or equivalent transactionally safe logic that re-checks eligibility at write time.

### FR-LIMIT — Maximum active tasks per assignee

- **FR-LIMIT-001:** A user may be assigned no more than ten active tasks at the same time.
- **FR-LIMIT-002:** Active tasks are those in `Backlog`, `In Progress`, or `Review`. `Todo` is not a distinct status.
- **FR-LIMIT-003:** Enforce the limit when creating a task with an assignee and when assigning/changing an assignee.
- **FR-LIMIT-004:** If assigning the task would cause the target assignee to exceed the limit, reject the operation with a validation/business-rule error and do not partially persist the change.
- **FR-LIMIT-005:** Tasks in `Done` and `Cancelled` do not count toward the active-task limit.
- **FR-LIMIT-006:** Concurrent assignment requests must not silently exceed the limit. The implementation must select an appropriate transaction/locking or equivalent consistency strategy. SQLite tests may not prove PostgreSQL locking behavior; this limitation must be documented.
- **FR-LIMIT-007:** Whether a currently assigned task is excluded from the target assignee's count when reassigning to the same assignee is an implementation detail that must be resolved consistently; it must not be counted twice. The intended result is that an update which does not change the assignee should not falsely exceed the limit.

### FR-DELETE — Soft deletion

- **FR-TASK-015:** Deletion must be soft deletion; the task's record and related data must not be physically removed by the normal delete endpoint.
- **FR-TASK-016:** A task must not be deleted while it is in `In Progress` or `Review`.
- **FR-TASK-017:** Soft deletion is allowed only when the task is in `Backlog`, `Done`, or `Cancelled`.
- **FR-TASK-018:** The soft-delete operation must persist a deletion marker and must not reset the task's creation metadata. Whether `updated_at` changes on soft deletion must be explicitly defined in implementation and tested; recommended behavior is to update it, but this is not yet an approved decision.
- **FR-TASK-019:** How soft-deleted tasks appear in list, detail, overdue, and statistics results is unresolved under DEC-05/DEC-13. Do not silently choose whether they remain visible or counted.
- **FR-TASK-020:** A soft-deleted task must not be eligible for automatic overdue cancellation.

### FR-COMMENT — Comments

- **FR-COMMENT-001:** A user with access to a task must be able to create a comment on that task.
- **FR-COMMENT-002:** A user with access to a task must be able to retrieve its comments.
- **FR-COMMENT-003:** A user may edit and delete comments created by that same user, subject to normal authentication and ownership checks.
- **FR-COMMENT-004:** The comment creator ID must be derived from the authenticated user, not trusted from the client body.
- **FR-COMMENT-005:** The final contract must define comment length limits and the behavior of comment operations for tasks in `Done`, `Cancelled`, or soft-deleted state. See DEC-14.

### FR-LIST — Search, filters, sorting, pagination

- **FR-LIST-001:** The task list must support case-insensitive substring search over both task title and description.
- **FR-LIST-002:** The list must support filtering by status, priority, assignee, and deadline range.
- **FR-LIST-003:** Multiple filters must be combined with logical `AND`.
- **FR-LIST-004:** The deadline range must support a lower and upper bound. Bound inclusion semantics must be settled under DEC-08.
- **FR-LIST-005:** The list must support sorting by creation date, deadline, and priority.
- **FR-LIST-006:** Ascending and descending sorting must be supported for each supported sort field. The exact query syntax and priority rank mapping must be documented under DEC-09.
- **FR-LIST-007:** Default sorting must order tasks by priority `High`, `Medium`, `Low`, then by nearest deadline first.
- **FR-LIST-008:** Tasks without a deadline must appear at the end of the default ordering.
- **FR-LIST-009:** The API must support page-number pagination with `page` and `page_size` parameters.
- **FR-LIST-010:** Pagination uses `page` default 1 and `page_size` default 20 with a maximum of 100.
- **FR-LIST-011:** Sorting must be deterministic across pages. A stable tie-breaker must be selected under DEC-15 before implementation.
- **FR-LIST-012:** List endpoints must enforce the final authorization and soft-delete visibility policy. The approved global task-visibility rule is that any authenticated user can view all tasks, subject to unresolved soft-delete handling.

### FR-OVERDUE — Overdue tasks endpoint

- **FR-OVERDUE-001:** The API must provide a dedicated endpoint that returns all overdue tasks across the system, irrespective of task author or assignee.
- **FR-OVERDUE-002:** A task is overdue when a due date is set, the due date is earlier than the current calendar date in `Europe/Kyiv`, and its status is not `Done` or `Cancelled`.
- **FR-OVERDUE-003:** A due date equal to today is not overdue during that date.
- **FR-OVERDUE-004:** Soft-deleted tasks are excluded from the overdue endpoint.
- **FR-OVERDUE-005:** Pagination for the overdue endpoint should follow the standard task-list pagination contract once DEC-07 is resolved.

### FR-STATS — Statistics endpoint

- **FR-STATS-001:** The API must provide global statistics for all tasks in the system, not merely the requesting user's tasks.
- **FR-STATS-002:** The response must include total task count.
- **FR-STATS-003:** The response must include counts grouped by every task status, including zero-count statuses.
- **FR-STATS-004:** The response must include counts grouped by every priority, including zero-count priorities.
- **FR-STATS-005:** The response must include overdue-task count using the definition in FR-OVERDUE.
- **FR-STATS-006:** The response must include active-task count, where active means `Backlog`, `In Progress`, or `Review`.
- **FR-STATS-007:** Soft-deleted tasks are excluded from every statistics field. The response must not use inconsistent inclusion rules across its statistics fields.

### FR-WORKER — Automatic overdue cancellation

- **FR-WORKER-001:** A separate deadline-worker process/service must run independently of incoming HTTP requests.
- **FR-WORKER-002:** The worker must perform an initial overdue-task check on startup to catch overdue tasks accumulated while the application was stopped.
- **FR-WORKER-003:** After startup processing, the worker must repeat the check periodically. The agreed default interval is five minutes (300 seconds), and the interval must be configurable via environment/configuration.
- **FR-WORKER-004:** The worker must select tasks with a non-null `due_date` earlier than the current calendar date in `Europe/Kyiv`, excluding soft-deleted tasks, and with a status of `Backlog`, `In Progress`, or `Review`.
- **FR-WORKER-005:** The worker must set matching tasks to `Cancelled` and update `updated_at`.
- **FR-WORKER-006:** The worker must not create comments, send notifications, or write a separate history event as part of overdue cancellation.
- **FR-WORKER-007:** Worker status changes must be safe under concurrency with API requests and must re-check the current status and due date when writing.
- **FR-WORKER-008:** A transient database/query error must be logged and must not permanently stop subsequent scheduled checks. Error handling must ensure the database session/transaction is cleaned up before the next attempt.
- **FR-WORKER-009:** A failed or interrupted run must be recoverable by a later run; overdue selection must be idempotent.
- **FR-WORKER-010:** The worker must wait for successful database migrations and database readiness before processing tasks.
- **FR-WORKER-011:** The worker interval and timezone configuration must be validated at startup and documented in the README.
- **FR-WORKER-012:** The application must not use FastAPI `BackgroundTasks` as the sole mechanism for this periodic workload. FastAPI `BackgroundTasks` may be used only for suitable request-triggered work if separately required later.

## 6. Proposed API surface

The following is a **proposed route layout** to make the requirements actionable. Exact route paths and some request/response details have not been separately approved; review them before treating the paths as immutable contracts. All routes use the `/api/v1/` prefix.

| Method | Proposed path | Purpose | Access |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | Register a user | Public |
| `POST` | `/api/v1/auth/login` | Obtain access and refresh tokens | Public |
| `POST` | `/api/v1/auth/refresh` | Rotate a refresh token and issue fresh tokens | Valid refresh token |
| `POST` | `/api/v1/auth/logout` | Revoke the supplied refresh token | Authenticated |
| `GET` | `/api/v1/tasks` | Search/filter/sort/page through tasks | Authenticated; visibility policy applies |
| `POST` | `/api/v1/tasks` | Create a task | Authenticated and authorized |
| `GET` | `/api/v1/tasks/overdue` | List overdue tasks across the system | Authenticated; global scope |
| `GET` | `/api/v1/tasks/statistics` | Return global task statistics | Authenticated; global scope |
| `GET` | `/api/v1/tasks/{task_id}` | Get one task | Authenticated; soft-delete policy applies |
| `PATCH` | `/api/v1/tasks/{task_id}` | Edit permitted task fields | Authorized |
| `DELETE` | `/api/v1/tasks/{task_id}` | Soft-delete an eligible task | Authorized; status rule applies |
| `PATCH` | `/api/v1/tasks/{task_id}/status` | Perform a validated status transition | Authorized; transition matrix applies |
| `GET` | `/api/v1/tasks/{task_id}/comments` | List task comments | Authenticated with task access |
| `POST` | `/api/v1/tasks/{task_id}/comments` | Create a comment | Authenticated with task access |
| `PATCH` | `/api/v1/comments/{comment_id}` | Edit own comment | Comment author |
| `DELETE` | `/api/v1/comments/{comment_id}` | Delete own comment | Comment author |
| `GET` | `/api/v1/health` | Health check | Public; returns no secrets |

Specific routes such as `/overdue` and `/statistics` must be registered so that they cannot be interpreted as dynamic task identifiers by route matching. The identifier type must be finalized under DEC-02.

### 6.1 Proposed list query parameters

The following query parameter names are approved:

- `q`: case-insensitive substring search in title and description.
- `status`: a valid task status; repeat the parameter to filter by multiple statuses.
- `priority`: a valid priority; repeat the parameter to filter by multiple priorities.
- `assignee_id`: filter by assigned user.
- `due_from`, `due_to`: lower and upper deadline bounds, both inclusive.
- `sort_by`: `created_at`, `due_date`, or `priority`.
- `sort_order`: `asc` or `desc`; priority ascending is `High` → `Medium` → `Low`.
- `page`, `page_size`: page-number pagination; defaults 1 and 20, maximum 100.

A single sort key is supported; custom sorting replaces the default order and `id ASC` is always the final tie-breaker. Do not interpolate user-provided query parameters into SQL text; validate them against an explicit allowlist.

## 7. Validation and error behavior

### 7.1 General validation

- Invalid enum values must be rejected.
- Invalid identifier formats must be rejected using the selected identifier type.
- Request validation must be implemented with Pydantic schemas and must not expose database internals.
- Server-managed fields must not be accepted as trusted values from clients.
- Partial-update semantics must distinguish an omitted field from an explicit `null` where clearing a value is allowed.
- All business checks must be enforced in the service/domain layer as well as represented in API validation where appropriate; they must not rely only on frontend/client behavior.

### 7.2 Standard errors

FastAPI's standard error response format is selected. The final endpoint contract must identify the expected HTTP status and `detail` for each failure, including at least:

- Missing, invalid, expired, or otherwise rejected authentication credentials.
- Insufficient role/ownership permissions.
- Invalid request field values.
- Resource not found or hidden under the soft-delete policy.
- Invalid status transition.
- Attempt to edit a terminal task.
- Attempt to change assignee after `Review`/`Done`.
- Completion without an assignee or after deadline.
- Attempt to exceed the active-task limit.
- Attempt to delete a task in `In Progress` or `Review`.
- Database or unexpected internal failures.

Exact status-code mapping remains open under DEC-12. Do not expose stack traces, raw SQL, access tokens, password hashes, or secret configuration in API errors.

## 8. Non-functional requirements

### NFR-SEC — Security

- **NFR-SEC-001:** Passwords must be securely hashed using an established password-hashing implementation.
- **NFR-SEC-002:** Authentication and authorization must be enforced server-side for every protected route.
- **NFR-SEC-003:** JWT signing secrets and database credentials must be supplied through environment/configuration and must not be committed to source control.
- **NFR-SEC-004:** Token validation must check signature, expiry, and relevant token claims. Refresh rotation must reject replayed/invalid refresh tokens according to the final token policy.
- **NFR-SEC-005:** Logs and error responses must not include passwords, password hashes, raw access/refresh tokens, or secrets.
- **NFR-SEC-006:** The project has not selected rate limiting, login throttling, email verification, or password reset. Do not represent these as implemented requirements.

### NFR-DATA — Data integrity

- **NFR-DATA-001:** Use Alembic for database schema migrations; do not rely on implicit table creation in production startup.
- **NFR-DATA-002:** Foreign-key relationships and uniqueness constraints must be represented in the schema where applicable.
- **NFR-DATA-003:** Task status and priority values must be constrained to their approved enumerations.
- **NFR-DATA-004:** Task mutations that must succeed or fail together must execute transactionally.
- **NFR-DATA-005:** The ten-active-task limit and worker/API race safety must be enforced at write time, not only by a prior unprotected read.
- **NFR-DATA-006:** Soft deletion must preserve the task record and its related data. Physical deletion is not part of the normal DELETE API behavior.

### NFR-REL — Reliability and lifecycle

- **NFR-REL-001:** Docker Compose must provide a reproducible local environment.
- **NFR-REL-002:** PostgreSQL health/readiness must be considered before migrations, API startup, and worker startup.
- **NFR-REL-003:** API and worker must not start processing against an unapplied schema.
- **NFR-REL-004:** The worker must perform startup catch-up and recover from transient errors by running future checks.
- **NFR-REL-005:** A worker run must be idempotent with respect to task status; repeated runs must not repeatedly modify tasks that are already `Cancelled` or `Done`.
- **NFR-REL-006:** Task status changes must not bypass the approved transition rules, except for the explicitly defined system-only overdue cancellation.

### NFR-OBS — Logging and health checks

- **NFR-OBS-001:** The application must emit useful application logs.
- **NFR-OBS-002:** A public health-check endpoint returns `{"status": "ok"}` and must not disclose secrets. A separate readiness/liveness distinction is not required.
- **NFR-OBS-003:** The worker must log startup, check start/end, number of tasks cancelled (or another non-sensitive summary), and recoverable errors.
- **NFR-OBS-004:** Logs should contain enough contextual information to diagnose a failed operation without recording credentials or unnecessary sensitive data.
- **NFR-OBS-005:** Distributed tracing, metrics, request IDs, and external monitoring have not been required.

### NFR-PERF — Performance

- **NFR-PERF-001:** No numeric latency, throughput, task-count, or concurrent-user target has been supplied.
- **NFR-PERF-002:** Queries must apply filters, ordering, and pagination at the database level rather than loading the entire task table into application memory.
- **NFR-PERF-003:** Statistics must be computed with database queries/aggregations where reasonable, not by fetching every task row into Python.
- **NFR-PERF-004:** Add indexes only where justified by query patterns and the final schema; candidate indexes include status, priority, due date, assignee, creation time, and soft-delete marker. Final index design should be reviewed after models and common query combinations are decided.

### NFR-MAINT — Maintainability

- **NFR-MAINT-001:** Use Python 3.13 and manage dependencies with `uv`.
- **NFR-MAINT-002:** Use Ruff for lint checks and formatting.
- **NFR-MAINT-003:** Prefer explicit typing, small cohesive functions, clear separation of HTTP/schema, business logic, persistence, and worker concerns. No separate static type checker is required by the approved pipeline.
- **NFR-MAINT-004:** Keep configuration outside source code and provide safe, explicit defaults only where they have been approved.
- **NFR-MAINT-005:** Use SQLAlchemy Async for database access and avoid blocking synchronous database calls in request/worker async paths.

### NFR-DOC — Documentation

- **NFR-DOC-001:** Provide a README with setup prerequisites, environment variables, local startup instructions, migration behavior, test commands, and common troubleshooting guidance.
- **NFR-DOC-002:** Include representative API request/response examples and document validation/business errors.
- **NFR-DOC-003:** OpenAPI/Swagger documentation must be accessible in development. Its exposure in production is not required and must be configurable/disabled as appropriate.
- **NFR-DOC-004:** Document the deadline worker's interval, time zone, startup catch-up behavior, and failure-recovery behavior.
- **NFR-DOC-005:** Document the test database limitation: SQLite is used for all tests although PostgreSQL is the production database.

## 9. Testing requirements and TDD workflow

### 9.1 General testing policy

- Pytest is required.
- All known business rules must be covered by automated tests; a minimum coverage percentage has not been requested.
- SQLite is the selected test database for all tests.
- Tests must include unit-level validation and API-level tests using the FastAPI application/test client compatible with the async stack.
- Tests must be deterministic and must not depend on live external services.
- Time-sensitive code should use an injectable/fake clock or another deterministic strategy so deadline boundary behavior can be tested without sleeping.

### 9.2 Required test coverage

At minimum, add tests for:

**Authentication and authorization**
- Successful registration and login.
- Invalid credentials and protected route access without a valid token.
- Refresh-token rotation and invalid/replayed refresh behavior once DEC-06 is finalized.
- Role and ownership cases for every protected task/comment operation once DEC-01 is finalized.

**Task CRUD and validation**
- Creating a valid task, including default priority.
- Invalid title/description and enum values once limits are finalized.
- Deadline `null`, today, and past-date cases.
- Server-managed fields cannot be spoofed by the client.
- Editing a task in each status, including prohibited edits in `Done` and `Cancelled`.
- Assignee immutability in `Review` and `Done`.
- Soft deletion in allowed and prohibited statuses.
- Soft-deleted resource behavior for list/detail/overdue/statistics after DEC-05 is finalized.

**Status transitions**
- Each approved valid transition succeeds.
- Every unlisted transition fails, including backward transitions and transitions out of terminal statuses.
- `Done` requires an assignee and respects the deadline boundary.
- Worker-only `Review -> Cancelled` is not made available to ordinary user requests.

**Active-task limit**
- Exactly ten active tasks can be assigned to one user.
- An operation that would create an eleventh active assignment fails without partial mutation.
- Tasks in `Done` and `Cancelled` do not count.
- Reassignment and assigning a task to the same user do not double-count the task.
- Concurrency semantics are tested to the extent SQLite supports them and the PostgreSQL limitation is explicitly noted.

**Search, filters, sorting, and pagination**
- Case-insensitive substring search over title and description.
- Each individual filter.
- Multiple filters combined with AND.
- Deadline-range boundaries.
- Sort by creation date, due date, and priority in both directions.
- Default priority/deadline ordering, including null deadlines at the end.
- Stable ordering and adjacent pagination pages without accidental duplicates caused by nondeterministic ordering.

**Comments**
- Creating and listing comments.
- Editing/deleting one's own comment.
- Denial of editing/deleting another user's comment.
- Finalized behavior for terminal and soft-deleted tasks.

**Overdue endpoint and statistics**
- Overdue criteria, including no deadline, today's due date, past due date, `Done`, and `Cancelled`.
- Global scope independent of author/assignee.
- Per-status and per-priority counts include zero-valued categories.
- Active count uses `Backlog`, `In Progress`, and `Review`.
- Soft-deleted inclusion rules, once finalized.

**Deadline worker**
- Startup catch-up.
- Periodic scheduling and configurable interval.
- Cancels overdue tasks in `Backlog`, `In Progress`, and `Review`.
- Does not change tasks that are not overdue, have no deadline, are soft-deleted, or are already `Done`/`Cancelled`.
- Updates `updated_at`.
- Retries future checks after a transient error.
- Safe conditional updates when the API concurrently changes a status.

### 9.3 TDD cycle

For each behavior change:

1. Add or adjust a test that describes the expected behavior and fails for the intended reason.
2. Implement the smallest change that makes the test pass.
3. Refactor without changing externally observable behavior.
4. Run the relevant tests, then the complete test suite when practical.
5. Run Ruff lint and Ruff format checks.
6. Review the diff and confirm that no unrelated changes or secrets are included.
7. Commit the completed task work with a clear Conventional Commit message.

Do not write implementation code first and retrofit tests afterward, except for an explicitly documented technical constraint approved by the maintainer.

## 10. CI and Git workflow requirements

### 10.1 Required checks

The GitHub Actions pipeline must provide at least these checks:

1. Commit-message format validation.
2. Ruff lint.
3. Ruff format check (check-only; CI must not silently rewrite files).
4. Pytest.

No static type checker is required by the approved scope. No numeric coverage threshold is required. CI must report failures with a non-zero exit code so failed checks can block a merge according to repository settings.

### 10.2 Commit messages

Use the approved Conventional Commit style based on the provided cheatsheet: https://gist.github.com/qoomon/5dfcdf8eec66a051ecd85625518cfd13

The accepted general form is:

```text
<type>(<optional-scope>): <description>

<optional body>

<optional footer>
```

- Scope is optional; do not enforce a fixed project scope allowlist.
- Use a concise, imperative, present-tense description.
- Start the description with a lowercase letter.
- Do not add a trailing period to the description.
- Use `!` before the colon to indicate a breaking change.
- Breaking changes must be documented in a `BREAKING CHANGE:` footer.
- The accepted type set is `feat`, `fix`, `refactor`, `perf`, `style`, `test`, `docs`, `build`, `ops`, and `chore`.
- A local `commit-msg` hook must provide fast feedback; GitHub Actions must independently validate commit messages.
- The gist's sample pre-receive regular expression contains a narrower type list than its cheatsheet. Implement the agreed full type list above rather than copying that narrower example verbatim.

### 10.3 Branch and merge workflow

- `develop` is the integration branch.
- Create one new branch per task from the latest `develop`.
- Branch format: `task/<task-id>-<short-description>`.
- Use lowercase kebab-case for the short description. Example: `task/12-deadline-worker`.
- Complete the task on its own branch, following TDD.
- Open a Pull Request targeting `develop` and pass required CI checks before merge.
- After a successful merge, remove the completed task branch according to repository policy.
- The next task must begin on a new branch from the latest `develop`.
- GitHub Actions runs on pushes to `develop` and on pull requests targeting `develop`. Changes merge using squash merge.

## 11. Docker Compose and configuration

### 11.1 Runtime behavior

- The application must be launchable using Docker Compose.
- PostgreSQL must use persistent storage for local development data, unless a disposable test profile is used.
- API and worker must connect to the configured PostgreSQL service, not to a hard-coded hostname outside the Compose network.
- Alembic migrations must execute automatically before API startup.
- The worker must not process tasks before the database is ready and migrations have succeeded.
- Failure to apply migrations must prevent API/worker startup rather than leave the stack in a partially upgraded state.
- A dedicated `migrate` Compose service runs `alembic upgrade head` after PostgreSQL is healthy; API and worker use `service_completed_successfully` on that service.

### 11.2 Configuration

All secrets and deployment-dependent settings must be provided through environment variables or a configuration mechanism documented in the README. At minimum, configuration must cover:

- Database connection URL or its constituent connection settings.
- JWT signing secret/key and algorithm configuration as appropriate.
- Access/refresh token lifetimes after DEC-06 is resolved.
- Deadline worker interval (default 300 seconds).
- Deadline time zone (`Europe/Kyiv`, approved).
- Application environment and API documentation exposure.
- Logging level if configurable.

Exact environment variable names should be chosen consistently in implementation and documented. Do not commit real credentials or secret values. Provide a safe example environment file with placeholder values only.

## 12. Acceptance criteria

The project is acceptable when all of the following are true:

1. The app starts from the documented Docker Compose command on a clean checkout after configuration is supplied.
2. Alembic migrations run automatically before API startup and failures prevent application startup.
3. Registration, login, access tokens, refresh rotation, and the finalized authorization matrix work and are tested.
4. Task fields, defaults, validation, CRUD, soft delete, and the finalized permission rules match this document.
5. Every approved status transition succeeds; every unapproved transition is rejected; `Done` validation is enforced.
6. The ten-active-task limit is enforced when creating/assigning tasks without partial persistence.
7. Comments obey ownership and access rules.
8. Search, filters, sorting, and pagination match the finalized contract and have automated coverage.
9. The overdue endpoint returns the globally scoped tasks matching the finalized overdue and soft-delete rules.
10. Statistics include total count, per-status counts, per-priority counts, overdue count, and active count using consistent inclusion rules.
11. The deadline worker performs startup catch-up and recurring checks, cancels eligible tasks, updates `updated_at`, and handles transient errors without silently stopping forever.
12. The worker cannot overwrite `Done` with `Cancelled` due to an API/worker race.
13. README documentation covers setup, configuration, migrations, endpoints, examples, errors, tests, and worker operation.
14. GitHub Actions validates commit messages, Ruff lint, Ruff formatting, and tests.
15. Local commit-message validation is configured.
16. Test coverage includes all confirmed business rules; no numeric coverage threshold is required.
17. No unresolved DEC item is silently replaced by an implementation assumption. Decisions required for a specific feature are resolved before that feature is implemented.

## 13. Decisions log

The following decisions have been explicitly approved:

- Versioned API prefix: `/api/v1/`.
- Authentication credentials: username and password.
- Public self-registration; registration assigns the `user` role.
- Roles: `user` and `admin`. A `user` manages only tasks they created; an `admin` manages all tasks. Comment editing/deletion is author-only.
- All authenticated users can view all non-deleted tasks globally.
- JWT access (15 minutes) and refresh (7 days) tokens with hashed refresh-token storage, rotation, revocation, and logout.
- No email verification or password-reset feature.
- Priorities: `High`, `Medium`, `Low`; default `Medium`.
- Optional deadline as a calendar date (not a datetime), interpreted in `Europe/Kyiv`.
- User-initiated transition matrix exactly as specified in FR-STATUS-003.
- `Todo` is a typo; use `Backlog`.
- Active assignee limit: 10 tasks in `Backlog`, `In Progress`, and `Review`; enforced during creation and assignment; reject an operation that would exceed the limit.
- Soft deletion; permitted statuses `Backlog`, `Done`, `Cancelled`; prohibited statuses `In Progress`, `Review`.
- Case-insensitive substring search over title/description; multiple filters combine with AND.
- Filter by status, priority, assignee, and deadline range.
- Sort by creation date, deadline, and priority; support ASC/DESC; default order High, Medium, Low then nearest deadline; null deadline last.
- Page-number pagination using `page` (default 1) and `page_size` (default 20, maximum 100).
- Overdue and statistics endpoints are global; soft-deleted tasks are excluded.
- FastAPI standard error-response structure with the status mapping approved in DEC-12.
- Separate periodic deadline worker; startup catch-up; default interval 5 minutes, configurable.
- The worker cancels overdue `Backlog`, `In Progress`, and `Review` tasks, updates status and `updated_at`, and creates no notifications/comments/history entries.
- Python 3.13, `uv`, Ruff, Pytest, GitHub Actions.
- SQLite for all tests, with its PostgreSQL-compatibility limitations documented.
- No static type checker and no numeric coverage threshold required.
- Alembic migrations must run automatically before API startup.
- Logs and a health check are required; no numeric performance targets.
- README with API examples and error rules; OpenAPI/Swagger available in development.
- TDD is mandatory.
- `develop` is the integration branch; each task gets a new branch named `task/<task-id>-<short-description>`, and the next task starts from the updated `develop` after the previous merge.
- Conventional Commit messages are checked by a local hook and GitHub Actions; use the accepted type set in Section 10.2.
