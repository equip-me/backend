# Rental Platform Backend

[![tests](https://github.com/khamitovdr/equipment-sharing-backend-v2/actions/workflows/coverage.yml/badge.svg)](https://github.com/khamitovdr/equipment-sharing-backend-v2/actions/workflows/coverage.yml)
[![coverage](https://coveralls.io/repos/github/khamitovdr/equipment-sharing-backend-v2/badge.svg?branch=main)](https://coveralls.io/github/khamitovdr/equipment-sharing-backend-v2?branch=main)
[![version](https://img.shields.io/badge/version-0.2.0-blue)](https://github.com/khamitovdr/equipment-sharing-backend-v2/pkgs/container/rental-platform)

B2B/B2C marketplace for renting equipment and assets. Organizations list rentable items, users browse the catalog and place rental orders, and the platform manages the full lifecycle — from request through pricing negotiation to active rental and completion.

Built with FastAPI, Tortoise ORM, and PostgreSQL.

## Key Features

- **Order lifecycle engine** — full state machine (pending → offered → confirmed → active → finished) with role-based transitions and cancellation flows

- **Organization management** — create, verify, and manage organizations with membership roles (admin/editor), invites, and Dadata integration for auto-filling legal data by INN

- **Listing catalog** — categorized equipment listings with draft/published lifecycle, public browsing, and org-scoped management

- **Media processing pipeline** — S3-compatible uploads (MinIO) with background processing via Redis-backed worker

- **Observability** — OpenTelemetry instrumentation with traces and metrics flowing to ClickHouse, visualized through pre-configured Grafana dashboards

- **JWT authentication** — Argon2id password hashing, token-based auth, platform roles (user/admin/owner) and org-level roles (admin/editor)

## Architecture

### Modules

| Module | Responsibility |
|--------|---------------|
| `users` | Registration, JWT auth, profiles, platform roles |
| `organizations` | Org CRUD, membership, Dadata integration |
| `listings` | Catalog browsing, categories, listing lifecycle |
| `orders` | Order state machine, rental lifecycle |
| `media` | S3 uploads, background image/video processing |
| `admin` | Platform admin endpoints (verify orgs, manage roles) |
| `observability` | OpenTelemetry setup, trace/metrics export |
| `core` | Shared infrastructure: config, DB, auth, enums |

### Infrastructure

Dev environment runs via Docker Compose:

| Service | Purpose |
|---------|---------|
| PostgreSQL 17 | Primary database |
| MinIO | S3-compatible object storage for media |
| Redis | Task queue for media processing worker |
| ClickHouse | Telemetry storage (traces, metrics) |
| OTel Collector | Receives and exports telemetry data |
| Grafana | Observability dashboards (localhost:3001) |

## Tech Stack

Python 3.14 · FastAPI · Pydantic v2 · Tortoise ORM (asyncpg) · PostgreSQL · MinIO · Redis · ClickHouse · OpenTelemetry · Grafana · Docker Compose · Poetry · Ruff · mypy · pytest · go-task

## Getting Started

Prerequisites: Python 3.14+, [Poetry](https://python-poetry.org/), [go-task](https://taskfile.dev/), Docker

```bash
git clone <repo-url>
cd equipment-sharing-backend-v2
cp .env.example .env        # fill in secrets
task setup                   # install dependencies
task dev                     # start infra + dev server + media worker
```

API docs: `http://localhost:8000/docs`

## Development

| Command | Purpose |
|---------|---------|
| `task dev` | Dev server + media worker (auto-starts infra) |
| `task ruff:fix` | Auto-fix lint + format |
| `task mypy` | Strict type checking |
| `task test` | Full test suite (auto-starts test infra) |
| `task ci` | ruff + mypy + test |

## Releases

Releases are cut via GitHub Actions workflows triggered manually:

- **`release-minor`** — run from `main`. Creates a `release/X.Y` branch, bumps the version, builds a Docker image, pushes to `ghcr.io`, and opens a PR to sync the version back to `main`.
- **`release-patch`** — run from a `release/X.Y` branch. Bumps the patch version, builds and pushes the image, pins it in `docker-compose.prod.yml`.

Images are published to `ghcr.io/khamitovdr/rental-platform` and tagged with the version number. The latest minor release also gets the `latest` tag.

## Links

- [Business Logic Spec](docs/business-logic.md) — full domain model, order state machine, permissions, and validation rules
- [Contributing](CONTRIBUTING.md) — branch workflow, PR format, coding conventions
