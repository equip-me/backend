# Rental Platform — Technical Specification

This document describes the technology stack, tooling, configuration, and development conventions for the new backend. Read alongside [business-logic.md](business-logic.md) which covers domain rules.

---

## Table of Contents

1. [Stack](#1-stack)
2. [Database](#2-database)
3. [Configuration](#3-configuration)
4. [Docker](#4-docker)
5. [Testing](#5-testing)
6. [Python Conventions](#6-python-conventions)
7. [Linting & Formatting (Ruff)](#7-linting--formatting-ruff)
8. [Type Checking (mypy)](#8-type-checking-mypy)
9. [Git Hooks](#9-git-hooks)
10. [Task Runner (go-task)](#10-task-runner-go-task)

---

## 1. Stack

Versions below are **minimum** (lower bounds). Use the latest available at the time of implementation; Poetry's lock file pins the exact versions.

| Package | Min version | Purpose |
|---------|-------------|---------|
| Python | 3.13 | Runtime |
| FastAPI | ≥ 0.135.2 | HTTP framework |
| Pydantic | ≥ 2.12.5 | Validation & serialization |
| pydantic-settings | ≥ 2.13.1 | App configuration (YAML + env vars) |
| Tortoise ORM (asyncpg) | ≥ 1.1.7 | Async ORM + PostgreSQL driver |
| dadata | ≥ 25.10.0 | Organization data auto-fill by INN |
| httpx | ≥ 0.28.1 | Async HTTP client |
| uvicorn | ≥ 0.42.0 | ASGI server (dev) |
| gunicorn | ≥ 25.1.0 | Process manager (prod, wrapping uvicorn workers) |
| pytest-cov | ≥ 7.1.0 | Test coverage reporting |
| ruff | ≥ 0.15.7 | Linting + formatting (replaces black, isort, flake8) |

**Dependency management:** Poetry. All configuration lives in `pyproject.toml`. The lock file (`poetry.lock`) **must be committed** — never gitignored.

---

## 2. Database

**PostgreSQL** — single relational database for all application data.

All models use UUID primary keys (see [business-logic.md § 6.1](business-logic.md#61-entity-relationships)).

Migrations are managed by Tortoise ORM's built-in migration framework (CLI: `tortoise`).

---

## 3. Configuration

Use **pydantic-settings** backed by **YAML config files**.

```
config/
├── base.yaml       # Shared defaults
├── dev.yaml        # Development overrides
├── test.yaml       # Test overrides
└── prod.yaml       # Production overrides
```

Environment selection: set `APP_ENV=dev|test|prod` (environment variable). The settings loader reads `base.yaml` first, then merges the environment-specific file on top.

Secrets (database password, JWT secret, Dadata API key) come from environment variables — never stored in YAML files.

### CORS

CORS allowed origins are managed in the YAML config files and passed to FastAPI's `CORSMiddleware`.

```yaml
# config/base.yaml
cors:
  allow_origins: []
  allow_methods: ["*"]
  allow_headers: ["*"]
  allow_credentials: true

# config/dev.yaml
cors:
  allow_origins: ["http://localhost:3000", "http://localhost:5173"]

# config/prod.yaml
cors:
  allow_origins: ["https://equip-me.ru", "https://www.equip-me.ru"]
```

---

## 4. Docker

### Compose files

Two Compose files with distinct purposes:

#### `docker-compose.yml` (development / CI)

Contains **only infrastructure services** needed to run tests locally — no application container.

| Service | Purpose |
|---------|---------|
| `db` | PostgreSQL instance for tests and local development |

The developer runs the application directly on the host (via `task run` or the IDE). Tests also run on the host against the containerized database.

#### `docker-compose.prod.yml` (production)

Full deployment stack for a VPS.

| Service | Purpose |
|---------|---------|
| `db` | PostgreSQL |
| `app` | Application (gunicorn + uvicorn workers) |

Production uses gunicorn as the process manager with uvicorn workers:

```bash
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Image build

The production image is built with a version tag passed as a build argument. This enables deploying specific releases on the VPS.

```dockerfile
# Dockerfile
FROM python:3.13-slim AS base

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}

# ... install deps, copy code ...
```

Build and tag:

```bash
task build VERSION=1.2.3
# equivalent to:
# docker build -t rental-platform:1.2.3 --build-arg APP_VERSION=1.2.3 .
# docker tag rental-platform:1.2.3 rental-platform:latest
```

The `APP_VERSION` is embedded in the image as an environment variable, accessible at runtime (e.g., for health-check endpoints or logging).

---

## 5. Testing

Comprehensive test coverage across three layers:

| Layer | What it tests | Database | External calls |
|-------|--------------|----------|---------------|
| **Unit** | Pure functions, validators, cost calculations, enum logic | No | No (mocked) |
| **DB** | CRUD operations, model constraints, queries, migrations | Yes (test DB) | No (mocked) |
| **Integration** | Full HTTP request → response through FastAPI `TestClient` | Yes (test DB) | Mocked |

### Test tooling

- **pytest** as the test runner
- **pytest-cov** for coverage reporting
- **httpx** `AsyncClient` with `ASGITransport` for integration tests
- **anyio** (asyncio backend) for async test support

### Conventions

- Each test file corresponds to one domain module (e.g., `test_users.py`, `test_orders.py`).
- Fixtures in `conftest.py` handle DB setup/teardown and provide pre-built entities (users, organizations, listings).
- Autouse fixture truncates all tables between tests for isolation.
- Coverage target: aim for high coverage but do not chase 100% — focus on business logic paths.

---

## 6. Python Conventions

### Hard rules

| Rule | Rationale |
|------|-----------|
| **No `# type: ignore`** | Fix the type error or restructure the code. |
| **No `from __future__ import annotations`** | Use runtime-evaluable annotations everywhere. Pydantic v2 and Tortoise rely on actual types at runtime. For forward references in return types, use `typing.Self` (Python 3.11+). |
| **Strict mypy** | Every function has full type annotations. No implicit `Any`. |
| **Poetry for dependency management** | Single `pyproject.toml` for deps, scripts, tool configs. |
| **Commit `poetry.lock`** | Reproducible installs across all environments. |
| **All tool config in `pyproject.toml`** | ruff, mypy, pytest, coverage — everything in one file. |

---

## 7. Linting & Formatting (Ruff)

Ruff handles both linting and formatting (replaces black + isort + flake8).

### `pyproject.toml` config

```toml
[tool.ruff]
target-version = "py313"
line-length = 119

[tool.ruff.format]
quote-style = "double"

[tool.ruff.lint]
select = ["ALL"]
ignore = [
    "D1",       # Missing docstrings — clear naming suffices for this project
    "PLR2004",  # Magic value comparison — protocol byte values are domain-intrinsic
    "ANN401",   # Disallowed `Any` — intentional for history values and Pydantic kwargs
    "COM812",   # Missing trailing comma — conflicts with ruff formatter
    "TRY003",   # Long exception messages — inline error messages are intentional
    "EM101",    # String literal in exception — fine for this project size
    "EM102",    # f-string in exception — same rationale
    "ARG002",   # Unused method argument — intentional for BaseDevice **kwargs passthrough
    "ARG005",   # Unused lambda argument — history callback lambdas
    "ERA001",   # Commented-out code — false positives
    "SLF001",   # Private member access — emulator._devices used by API routes intentionally
    "PLR0911",  # Too many return statements — protocol dispatch functions are inherently branchy
    "PLR0913",  # Too many arguments — BaseDevice.__init__ needs them all
    "C901",     # Too complex — protocol dispatch functions are inherently complex
    "SIM108",   # Ternary operator — if/else is clearer when branches have comments
    "A005",     # Module shadowing stdlib — core/types.py is intentional
    "D203",     # Incompatible with D211
    "D213",     # Incompatible with D212
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = [
    "S101",     # assert usage — this is pytest
    "PT018",    # Composite assertions — fine for protocol verification
    "SLF001",   # Private member access — tests legitimately inspect internals
    "PT011",    # pytest.raises too broad — acceptable here
    "PT015",    # Assert always false — "should have raised" pattern
    "B011",     # Same as PT015
    "PLR2004",  # Magic values in test assertions
    "N801",     # Class naming — test classes mirror function names like TestUint16_2Bytes
    "SIM117",   # Nested with — yield inside nested async with can't be combined
]
```

---

## 8. Type Checking (mypy)

Strict mode enabled. All code must pass without `# type: ignore` comments.

```toml
[tool.mypy]
python_version = "3.13"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
show_error_codes = true

[[tool.mypy.overrides]]
module = ["tortoise.*"]
ignore_missing_imports = true
```

The `ignore_missing_imports` override is limited to libraries that lack type stubs. Application code itself must be fully typed.

---

## 9. Git Hooks

Managed via **pre-commit**. Hook commands delegate to `task` for consistency.

### Pre-commit hook (runs on every commit)

| Step | Command | Purpose |
|------|---------|---------|
| 1 | `task lint:fix` | ruff check --fix + ruff format |
| 2 | `task typecheck` | mypy strict check |

### Pre-push hook (runs before push to `main`)

| Step | Command | Purpose |
|------|---------|---------|
| 1 | `task test` | Full test suite; push is blocked if any test fails |

### `.pre-commit-config.yaml`

```yaml
repos:
  - repo: local
    hooks:
      - id: lint-fix
        name: ruff lint + format
        entry: task lint:fix
        language: system
        types: [python]
        pass_filenames: false

      - id: mypy
        name: mypy
        entry: task typecheck
        language: system
        types: [python]
        pass_filenames: false

  - repo: local
    hooks:
      - id: pytest-on-push
        name: pytest (pre-push)
        entry: task test
        language: system
        stages: [pre-push]
        pass_filenames: false
```

Install hooks after cloning:

```bash
task setup
```

---

## 10. Task Runner (go-task)

All development commands are automated via [go-task](https://taskfile.dev/) (`Taskfile.yml` at repo root). This is the single entry point for running, testing, linting, building, and deploying.

### `Taskfile.yml`

```yaml
version: "3"

vars:
  IMAGE_NAME: rental-platform
  VERSION: dev

tasks:
  # ── Setup ──────────────────────────────────────────────
  setup:
    desc: Install deps, set up hooks, start infra
    cmds:
      - poetry install
      - poetry run pre-commit install
      - poetry run pre-commit install --hook-type pre-push
      - task: infra:up

  # ── Infrastructure ─────────────────────────────────────
  infra:up:
    desc: Start dev infrastructure (DB)
    cmds:
      - docker compose up -d

  infra:down:
    desc: Stop dev infrastructure
    cmds:
      - docker compose down

  infra:reset:
    desc: Stop dev infrastructure and remove volumes
    cmds:
      - docker compose down -v

  # ── Run ────────────────────────────────────────────────
  run:
    desc: Start the dev server
    cmds:
      - poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

  # ── Lint & Format ──────────────────────────────────────
  lint:
    desc: Check linting (no auto-fix)
    cmds:
      - poetry run ruff check .
      - poetry run ruff format --check .

  lint:fix:
    desc: Auto-fix lint errors and format
    cmds:
      - poetry run ruff check --fix .
      - poetry run ruff format .

  # ── Type checking ──────────────────────────────────────
  typecheck:
    desc: Run mypy strict
    cmds:
      - poetry run mypy .

  # ── Testing ────────────────────────────────────────────
  test:
    desc: Run full test suite
    cmds:
      - poetry run pytest

  test:cov:
    desc: Run tests with coverage report
    cmds:
      - poetry run pytest --cov=app --cov-report=html --cov-report=term

  test:lf:
    desc: Re-run last failed tests
    cmds:
      - poetry run pytest --lf

  # ── Database migrations ────────────────────────────────
  db:init:
    desc: Create migration packages (first-time setup)
    cmds:
      - poetry run tortoise init

  db:makemigrations:
    desc: Detect model changes and generate migrations
    cmds:
      - poetry run tortoise makemigrations

  db:migrate:
    desc: Apply pending migrations
    cmds:
      - poetry run tortoise migrate

  # ── Build & Deploy ─────────────────────────────────────
  build:
    desc: Build production Docker image (pass VERSION=x.y.z)
    cmds:
      - docker build -t {{.IMAGE_NAME}}:{{.VERSION}} --build-arg APP_VERSION={{.VERSION}} .
      - docker tag {{.IMAGE_NAME}}:{{.VERSION}} {{.IMAGE_NAME}}:latest

  deploy:
    desc: Deploy to production (pass VERSION=x.y.z)
    cmds:
      - task: build
      - docker compose -f docker-compose.prod.yml up -d

  # ── CI (all checks) ───────────────────────────────────
  ci:
    desc: Run all checks (lint + typecheck + test)
    cmds:
      - task: lint
      - task: typecheck
      - task: test
```

### Quick reference

| Command | What it does |
|---------|-------------|
| `task setup` | Install deps, hooks, start DB |
| `task run` | Start dev server with hot reload |
| `task lint` | Check lint (no changes) |
| `task lint:fix` | Auto-fix + format |
| `task typecheck` | mypy strict |
| `task test` | Run all tests |
| `task test:cov` | Tests with coverage report |
| `task test:lf` | Re-run last failed tests |
| `task db:init` | Create migration packages (first time) |
| `task db:makemigrations` | Generate migration from model changes |
| `task db:migrate` | Apply pending migrations |
| `task build VERSION=1.2.3` | Build tagged production image |
| `task deploy VERSION=1.2.3` | Build + deploy to production |
| `task ci` | Full CI pipeline (lint + types + tests) |
| `task infra:up` | Start dev DB |
| `task infra:down` | Stop dev DB |
| `task infra:reset` | Stop dev DB + wipe volumes |
