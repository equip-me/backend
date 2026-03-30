# Rental Platform Backend

[![tests](https://github.com/khamitovdr/equipment-sharing-backend-v2/actions/workflows/coverage.yml/badge.svg)](https://github.com/khamitovdr/equipment-sharing-backend-v2/actions/workflows/coverage.yml)
[![coverage](https://coveralls.io/repos/github/khamitovdr/equipment-sharing-backend-v2/badge.svg?branch=main)](https://coveralls.io/github/khamitovdr/equipment-sharing-backend-v2?branch=main)
[![version](https://img.shields.io/badge/version-0.1.0-blue)](https://github.com/khamitovdr/equipment-sharing-backend-v2/pkgs/container/rental-platform)

B2B/B2C marketplace for renting equipment and assets. Organizations list rentable items, users browse the catalog and place rental orders, and the platform manages the full order lifecycle from request through active rental to completion.

Built with FastAPI, Tortoise ORM, and PostgreSQL.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.14 |
| Framework | FastAPI + Pydantic v2 |
| ORM | Tortoise ORM (asyncpg) |
| Database | PostgreSQL |
| Auth | JWT (HS256) + Argon2id password hashing |
| Config | YAML + Pydantic |
| External APIs | Dadata (organization legal data by INN) |
| Dependency mgmt | Poetry |
| Linting/Formatting | Ruff |
| Type checking | mypy (strict) |
| Testing | pytest + httpx AsyncClient + anyio |
| Task runner | go-task |
| Production | gunicorn + uvicorn workers, Docker |

## Architecture

### Project Layout

```
app/                    # Application code
├── main.py             # FastAPI entrypoint (app.main:app)
├── core/               # Shared infrastructure (config, DB, auth, enums)
├── users/              # User registration, auth, profiles
├── organizations/      # Org management, membership, verification
├── listings/           # Catalog, categories, listing lifecycle
└── orders/             # Order state machine, rental lifecycle
config/                 # YAML config: base.yaml, dev.yaml, test.yaml, prod.yaml
tests/                  # Unit, DB, and integration tests
docs/                   # Business logic and technical specifications
```

### Domain Modules

| Module | Responsibility | API Prefix |
|--------|---------------|------------|
| **Users** | Registration, JWT auth, profiles, platform roles | `/users/` |
| **Organizations** | Org CRUD, membership (join/invite), Dadata integration | `/organizations/{org_id}/` |
| **Listings** | Catalog browse, categories, listing lifecycle | `/listings/`, `/organizations/{org_id}/listings/` |
| **Orders** | Order state machine (pending → offered → confirmed → active → finished) | `/orders/`, `/organizations/{org_id}/orders/` |
| **Private** | Platform admin endpoints (verify orgs, manage roles) | `/private/` |

## Getting Started

### Prerequisites

- Python 3.14+
- [Poetry](https://python-poetry.org/docs/#installation)
- [go-task](https://taskfile.dev/installation/)
- Docker & Docker Compose

### Setup

```bash
git clone <repo-url>
cd equipment-sharing-backend-v2
cp .env.example .env   # fill in secrets (DB password, JWT secret, Dadata key)
task setup              # installs deps, starts dev + test DBs
```

### Run

```bash
task run                # uvicorn dev server at http://localhost:8000
```

API docs are available at `http://localhost:8000/docs` (Swagger UI).

## Development Commands

All commands use [go-task](https://taskfile.dev/). Run `task --list` to see all available tasks.

| Command | Purpose |
|---------|---------|
| `task setup` | Install deps, start dev + test DBs |
| `task run` | Dev server with hot reload |
| **Lint & Types** | |
| `task lint` | Check lint (no changes) |
| `task lint:fix` | Auto-fix + format |
| `task typecheck` | mypy strict |
| **Testing** | |
| `task test` | Full test suite |
| `task test:cov` | Tests with coverage report |
| `task test:lf` | Re-run last failed tests |
| **Database** | |
| `task db:makemigrations` | Generate migration from model changes |
| `task db:migrate` | Apply pending migrations |
| **Infrastructure** | |
| `task infra:up` | Start dev DB |
| `task infra:down` | Stop dev DB |
| `task infra:reset` | Stop dev DB + wipe volumes |
| `task ci` | Full CI pipeline (lint + types + tests) |

## Configuration

The app uses layered YAML configuration. Set `APP_ENV` to select the environment:

| `APP_ENV` | Config files loaded | Use case |
|-----------|-------------------|----------|
| `dev` | `base.yaml` + `dev.yaml` | Local development |
| `test` | `base.yaml` + `test.yaml` | Test suite |
| `prod` | `base.yaml` + `prod.yaml` | Production |

Config files live in `config/`. The loader merges `base.yaml` (shared defaults) with the environment-specific file.

### Secrets

Secrets are provided via environment variables only — never in YAML files:

| Variable | Purpose |
|----------|---------|
| `DATABASE_PASSWORD` | PostgreSQL password |
| `JWT_SECRET` | JWT signing key |
| `DADATA_API_KEY` | Dadata API key (org data by INN) |

See `.env.example` for the full list.

## Testing

Three test layers, each with a clear boundary:

| Layer | What it tests | Database | External calls |
|-------|--------------|----------|---------------|
| **Unit** | Pure functions, validators, cost calculations | No | Mocked |
| **DB** | CRUD, model constraints, queries, migrations | Yes (test DB) | Mocked |
| **Integration** | Full HTTP request → response via AsyncClient | Yes (test DB) | Mocked |

```bash
task infra:up             # ensure dev DB is running
task test                 # run all tests
task test:cov             # with coverage report (HTML + terminal)
task test:lf              # re-run last failed only
```

Tests live in `tests/` and use `APP_ENV=test` automatically (configured in `pyproject.toml`). The test database runs on port **5433** to avoid conflicts with the dev DB.

## Docker

### Development

Development uses Docker only for infrastructure (PostgreSQL). The app runs directly on the host:

```bash
task infra:up       # start PostgreSQL (port 5432)
task run            # start app on host
```

Compose files:
- `docker-compose.dev.yml` — dev DB (port 5432)
- `docker-compose.test.yml` — test DB (port 5433)

### Production

Full stack in Docker — PostgreSQL + app (gunicorn with uvicorn workers).

Releases are built and published via GitHub Actions (`release-minor` / `release-patch` workflows). Images are pushed to `ghcr.io` and pinned in `docker-compose.prod.yml` on the release branch.

On the server:

```bash
git checkout release/X.Y     # the release branch you want to deploy
git pull
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

Secrets are passed via environment variables to the container.

## API Overview

| Prefix | Purpose | Auth |
|--------|---------|------|
| `POST /users/` | Registration | Public |
| `GET /users/me` | Current user profile | Authenticated |
| `/organizations/{org_id}/` | Org management, members | Authenticated / Org roles |
| `/organizations/{org_id}/listings/` | Manage org's listings | Org Editor |
| `/organizations/{org_id}/orders/` | Process incoming orders | Org Editor |
| `/listings/` | Public catalog browse | Public |
| `/orders/` | User-side order actions | Authenticated |
| `/private/` | Platform admin (verify orgs, manage roles) | Platform Admin |

### Permission Levels

| Level | Requirement |
|-------|-------------|
| Public | None |
| Authenticated | Valid JWT, not suspended |
| Org Editor | Authenticated + editor/admin membership |
| Org Admin | Authenticated + admin membership |
| Platform Admin | Authenticated + admin/owner role |

Full business logic and order state machine: [`docs/business-logic.md`](docs/business-logic.md)
Technical specification: [`docs/technical-spec.md`](docs/technical-spec.md)

## Contributing

All changes go through pull requests — `main` is protected and requires squash merge.

### Workflow

1. Create a branch: `type/short-description` (e.g. `feat/jwt-refresh-tokens`)
2. Run `task lint:fix` and `task typecheck` before pushing
3. Open a PR with a [Conventional Commits](https://www.conventionalcommits.org/) title (max 72 chars)

PR title format: `type(scope): description` or `type: description`

Allowed types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`, `perf`

### CI

GitHub Actions runs on every PR to `main`:
- **lint** — ruff check + format
- **typecheck** — mypy strict
- **test** — pytest with Postgres
- **pr-title** — Conventional Commits validation

All checks must pass before merge. Coverage is reported separately on `main` after merge.

Run everything locally before pushing:

```bash
task ci   # lint + typecheck + test
```

### Conventions

- **Type annotations** on every function — strict mypy, no `# type: ignore`
- **No `from __future__ import annotations`** — Pydantic v2 and Tortoise need runtime types
- **Ruff** handles linting and formatting (replaces black + isort + flake8)
- **Poetry** for all dependency management — commit `poetry.lock`
- **All tool config** lives in `pyproject.toml`
