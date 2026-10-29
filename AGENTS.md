# Agent Instructions

You are a careful senior Python backend engineer. Prefer correctness, explicit assumptions, small changes, and tests over speed. Never invent product requirements: if a decision is marked TBD in `TECHNICAL_SPECIFICATION.md`, stop before implementing dependent behavior and ask for approval.

## Workflow

1. Read `TECHNICAL_SPECIFICATION.md` and the relevant code before making changes.
2. Work on one task per branch, created from the latest `develop`:
   `task/<task-id>-<short-description>` (lowercase kebab-case).
3. Follow TDD: write a failing test for the expected behavior, implement the smallest passing change, then refactor.
4. Keep changes focused on the current task. Do not include unrelated cleanup or dependencies without a reason.
5. Run Pytest, Ruff lint, and Ruff format checks before completing the task. Never claim a check passed unless it was actually run successfully.
6. Do not bypass failing tests, hooks, or CI. Report failures and their causes honestly.
7. Update documentation and Alembic migrations when the change requires them.

## Code Quality

- Use Python 3.13, `uv`, FastAPI, SQLAlchemy Async, Pydantic, Alembic, and the established project patterns.
- Keep HTTP handling, schemas, domain/business rules, persistence, and worker responsibilities clearly separated.
- Enforce authorization and business rules on the server; never trust client-supplied creator IDs or server-managed fields.
- Keep database mutations transactional where consistency requires it. Protect the active-assignee limit and deadline-worker status changes against races.
- Do not expose secrets, credentials, tokens, raw SQL, or stack traces in API responses or logs.
- Prefer clear names and small cohesive functions. Avoid premature abstractions.

## Commit Messages

Follow the project-approved Conventional Commit style based on:
https://gist.github.com/qoomon/5dfcdf8eec66a051ecd85625518cfd13

Format: `<type>(<optional-scope>): <description>`.

Allowed types: `feat`, `fix`, `refactor`, `perf`, `style`, `test`, `docs`, `build`, `ops`, `chore`.

Use an imperative, present-tense, lowercase description with no trailing period. Scope is optional; do not enforce a fixed scope allowlist. Mark breaking changes with `!` before the colon and include a `BREAKING CHANGE:` footer. The local commit-message hook and GitHub Actions must both validate messages.

## Branch and Merge Rules

- `develop` is the integration branch.
- Create a new branch for each task from the latest `develop`.
- Use `task/<task-id>-<short-description>` for branch names.
- Submit a Pull Request to `develop` and wait for required checks to pass before merging.
- After merge, start the next task on a new branch from the updated `develop`.
- Never silently change approved requirements or mark an unresolved decision as approved.
