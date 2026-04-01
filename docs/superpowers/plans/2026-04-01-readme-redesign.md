# README Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stale README with a feature-forward version and extract contributing guidelines into a dedicated file.

**Architecture:** Two static documentation files. README leads with features and architecture, ends with quick start. CONTRIBUTING.md holds the workflow, PR format, CI, and coding conventions extracted from the current README.

**Tech Stack:** Markdown

---

### Task 1: Write the new README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace README.md with the new content**

```markdown
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

## Links

- [Business Logic Spec](docs/business-logic.md) — full domain model, order state machine, permissions, and validation rules
- [Contributing](CONTRIBUTING.md) — branch workflow, PR format, coding conventions
```

- [ ] **Step 2: Review the rendered output**

Open `README.md` in a Markdown previewer or on GitHub to verify badges render, tables align, and links work.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README with feature-forward structure"
```

---

### Task 2: Create CONTRIBUTING.md

**Files:**
- Create: `CONTRIBUTING.md`

- [ ] **Step 1: Write CONTRIBUTING.md**

```markdown
# Contributing

All changes go through pull requests — `main` is protected and requires squash merge. The PR title becomes the commit message on `main`, so it must be clear and well-structured.

## Workflow

1. Create a branch: `type/short-description` (e.g. `feat/jwt-refresh-tokens`, `fix/order-status-race`)
2. Run `task ruff:fix` and `task mypy` before pushing
3. Open a PR with a [Conventional Commits](https://www.conventionalcommits.org/) title

## PR Title Format

Format: `type(scope): description` or `type: description` — max 72 characters.

Allowed types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`, `perf`

Examples:
- `feat(auth): add JWT refresh token rotation`
- `fix: prevent duplicate order creation on retry`
- `refactor(listings): extract price calculation service`

## PR Description

```
## Summary
<1-3 bullet points: what changed and why>

## Test plan
<How to verify: new/updated tests, manual steps, or N/A>
```

## CI

GitHub Actions runs on every PR to `main`:

- **lint** — `ruff check` + `ruff format --check`
- **typecheck** — mypy strict
- **test** — pytest with Postgres
- **pr-title** — Conventional Commits validation

All checks must pass before merge.

Run everything locally first:

```bash
task ci   # ruff + mypy + test
```

## Conventions

- **Type annotations** on every function — strict mypy, no `# type: ignore`
- **No `from __future__ import annotations`** — Pydantic v2 and Tortoise need runtime types
- **Ruff** handles linting and formatting (replaces black + isort + flake8)
- **Poetry** for dependency management — commit `poetry.lock`
- **All tool config** lives in `pyproject.toml`
```

- [ ] **Step 2: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs: extract contributing guidelines to CONTRIBUTING.md"
```
