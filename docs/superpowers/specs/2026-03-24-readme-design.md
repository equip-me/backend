# README Design Spec

**Date:** 2026-03-24
**Approach:** Concise Developer Reference (Approach A)
**Audience:** Developers / team members
**Language:** English
**Scope:** Full planned system (all domain modules)

---

## Design Decisions

- **No duplication** — the README references `docs/business-logic.md` and `docs/technical-spec.md` for detailed specs rather than repeating their content.
- **Tables over prose** — most sections use tables for scannability.
- **Task runner as single entry point** — all commands go through `task`, so the README documents task commands rather than raw Poetry/Docker commands.
- **Secrets via env vars only** — the README mentions `.env.example` and lists secret variable names but never includes actual values.

---

## Sections

### 1. Header & Project Description

One-line project name, two-sentence description of the platform (B2B/B2C equipment rental marketplace), stack callout (FastAPI + Tortoise ORM + PostgreSQL).

### 2. Tech Stack

Single table mapping layers (Language, Framework, ORM, Database, Auth, Config, External APIs, Dependency mgmt, Linting, Type checking, Testing, Task runner, Production) to their technologies. No version numbers — those live in `pyproject.toml`.

### 3. Architecture

Two sub-sections:

- **Project Layout** — directory tree showing `app/` (with `core/`, `users/`, `organizations/`, `listings/`, `orders/`), `config/`, `tests/`, `docs/`.
- **Domain Modules** — table with module name, responsibility, and API prefix for each: Users, Organizations, Listings, Orders, Private.

### 4. Getting Started

- **Prerequisites:** Python 3.13+, Poetry, go-task, Docker & Docker Compose.
- **Setup:** clone, `cp .env.example .env`, `task setup`.
- **Run:** `task run`, mention Swagger UI at `/docs`.

### 5. Development Commands

Single table of all `task` commands grouped by category (bold separator rows): Setup, Lint & Types, Testing, Database, Infrastructure, Build & Deploy.

### 6. Configuration

- Explanation of layered YAML config via pydantic-settings.
- Table of `APP_ENV` values (`dev`, `test`, `prod`) with which config files are loaded.
- Secrets table: `DB_PASSWORD`, `JWT_SECRET`, `DADATA_API_KEY` with purpose descriptions.
- Pointer to `.env.example`.

### 7. Testing

- Three-layer table (Unit, DB, Integration) showing what each tests, whether it uses a database, and how external calls are handled.
- Commands: `task test`, `task test:cov`, `task test:lf`.
- Note about test DB on port 5433.

### 8. Docker

Two sub-sections:

- **Development** — Docker for infra only (PostgreSQL). App runs on host. Lists compose files: `docker-compose.dev.yml` (port 5432), `docker-compose.test.yml` (port 5433).
- **Production** — full stack in Docker (gunicorn + uvicorn workers). `task build VERSION=x.y.z` and `task deploy VERSION=x.y.z`. Uses `docker-compose.prod.yml`.

### 9. API Overview

- Route prefix table with purpose and auth level for each group: `/users/`, `/organizations/{org_id}/`, `/listings/`, `/orders/`, `/private/`.
- Permission levels table: Public, Authenticated, Org Editor, Org Admin, Platform Admin.
- Links to `docs/business-logic.md` and `docs/technical-spec.md`.

### 10. Contributing

- **Code Quality Gates:** pre-commit (lint:fix + typecheck), pre-push (test). Manual: `task ci`.
- **Conventions:** strict mypy with full type annotations, no `# type: ignore`, no `from __future__ import annotations`, Ruff for linting/formatting, Poetry for deps, all config in `pyproject.toml`.
