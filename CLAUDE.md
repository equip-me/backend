# Rental Platform Backend

B2B/B2C marketplace for renting equipment. FastAPI + Tortoise ORM + PostgreSQL.

## Stack

- Python 3.14, FastAPI, Pydantic v2, Tortoise ORM (asyncpg), pydantic-settings (YAML)
- Dependency management: Poetry (`pyproject.toml` + committed `poetry.lock`)
- Linting/formatting: Ruff (replaces black, isort, flake8)
- Type checking: mypy strict
- Testing: pytest + httpx AsyncClient + anyio
- Task runner: go-task (`Taskfile.yml`)

## Project Layout

```
config/              # YAML config: base.yaml, dev.yaml, test.yaml, prod.yaml
app/                 # Application code
  main.py            # FastAPI app entrypoint (app.main:app)
tests/               # Tests (unit, db, integration)
docs/                # Specs: technical-spec.md, business-logic.md
```

## Key Commands

| Command | Purpose |
|---------|---------|
| `task setup` | Install dependencies |
| `task dev` | Dev server + media worker (auto-starts infra) |
| `task ruff:fix` | Auto-fix lint + format |
| `task mypy` | Strict type checking |
| `task test` | Full test suite (auto-starts test infra) |
| `task db:makemigrations` | Generate migration |
| `task db:migrate` | Apply migrations |
| `task ci` | ruff + mypy + test |

## Configuration

`APP_ENV=dev|test|prod` selects config. Loader merges `base.yaml` + env-specific file.
Secrets (DB password, JWT secret, Dadata key) come from env vars only.

## Business Logic

Full domain spec (entities, enums, state machines, permissions, API routes): `docs/business-logic.md`

Read it when you need domain model details, validation rules, order lifecycle, or permission logic.
External integrations: Dadata (org data by INN).

## Contributing

### Branch Protection

`main` is protected. All changes go through pull requests with squash merge.
The PR title becomes the commit message on `main`, so it must be clear and well-structured.

### Workflow

1. Create a feature branch: `type/short-description` (e.g. `feat/jwt-refresh-tokens`, `fix/order-status-race`)
2. Run `task ruff:fix` and `task mypy` locally before pushing
3. Open a PR via `gh pr create` with a Conventional Commits title and a detailed body

### PR Title (Conventional Commits)

Format: `type(scope): description` or `type: description` — max 72 characters.

Allowed types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`, `perf`

Good examples:
- `feat(auth): add JWT refresh token rotation`
- `fix: prevent duplicate order creation on retry`
- `refactor(listings): extract price calculation service`

Bad examples:
- `Update code` (no type, vague)
- `feat: Implement the new user registration flow with email verification and admin approval` (too long)

### PR Description Template

```
## Summary
<1-3 bullet points: what changed and why>

## Test plan
<How to verify: new/updated tests, manual steps, or N/A>
```

### Commit Messages

- Do not mention Claude Code or AI tools in commit messages or `Co-Authored-By` trailers.

### CI

GitHub Actions runs on every PR to `main`:
- **lint** — `ruff check` + `ruff format --check`
- **typecheck** — `mypy`
- **test** — `pytest` (with Postgres service)
- **pr-title** — Conventional Commits format validation

All four checks must pass before merge. Coverage report runs separately on `main` after merge.

## Python Conventions

### Hard Rules

- **No `# type: ignore`** — fix the type error or restructure
- **No `from __future__ import annotations`** — Pydantic v2 and Tortoise need runtime types. Use `typing.Self` for forward refs
- **Strict mypy** — every function fully typed, no implicit `Any`
- **All config in `pyproject.toml`** — ruff, mypy, pytest, coverage
- **Ruff** — line length 119, `select = ["ALL"]` with specific ignores (see pyproject.toml)

### Patterns

- 6-char short string IDs (`CharField(max_length=6)`) on user-facing models (User, Organization, Listing, ListingCategory, Order); UUID on internal models
- Async everywhere (Tortoise ORM is async-native)
- Pydantic v2 schemas for request/response

### Testing Layers

| Layer | DB | External |
|-------|-------|----------|
| Unit | No | Mocked |
| DB | Test DB | Mocked |
| Integration | Test DB | Mocked |

- httpx `AsyncClient` + `ASGITransport` for integration tests
- Fixtures in `conftest.py`, autouse table truncation between tests

## Orchestration

### Python Subagents
When dispatching subagents for Python implementation, include the full Python Conventions section in the subagent prompt.

### Business Logic Changes
When brainstorming introduces new entities, changes workflows, or modifies permissions:
1. After design is approved by user, before writing the implementation plan
2. Update `docs/business-logic.md` to reflect the target state
3. Dispatch a reviewer subagent to verify the doc changes
4. Ask user to review before proceeding to implementation plan
