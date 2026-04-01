# README Redesign Spec

## Context

The current README (~245 lines) is a full developer handbook that has gone stale as the project
evolved. Task commands, project layout, and infrastructure descriptions no longer match reality.
Several major features (media pipeline, observability stack, admin module) are missing entirely.

## Goals

- **Primary audience**: developers evaluating the project, then onboarding
- **Tone**: professional but warm — brief explanations of *why*, not just *what*
- **Structure**: Feature-Forward (Approach A) — lead with what the platform does and what makes
  it interesting, quick "get started" at the bottom

## Design Decisions

- **Contributing section** → extracted to a separate `CONTRIBUTING.md`; README links to it
- **Deployment/Docker details** → minimal mention only; deployment docs belong elsewhere
- **Observability stack** → highlighted as a feature (not hidden as an implementation detail)
- **Tech stack** → single-line flow instead of a table (lighter, more scannable)
- **File tree** → removed (duplicates the module table)
- **Commands table** → only the 5 essential commands, matching actual Taskfile

## README Structure

### 1. Header Block

Title, badges (tests, coverage, version), one-liner description, tech callout.

### 2. Key Features

Six bullets, each with a brief "why it matters" clause:

- Order lifecycle engine (state machine with role-based transitions)
- Organization management (membership roles, Dadata integration)
- Listing catalog (draft/published lifecycle, public browsing)
- Media processing pipeline (MinIO + Redis worker)
- Observability (OTel → ClickHouse → Grafana)
- JWT authentication (Argon2id, platform + org-level roles)

### 3. Architecture

Two subsections:

**Modules table** — 8 rows: users, organizations, listings, orders, media, admin, observability, core.

**Infrastructure table** — 6 rows: PostgreSQL, MinIO, Redis, ClickHouse, OTel Collector, Grafana.

### 4. Tech Stack

Single-line inline list of all technologies.

### 5. Getting Started

Prerequisites line + 5-line code block (clone, cd, env, setup, dev). Link to Swagger UI.

### 6. Development

Compact table with 5 commands: `task dev`, `task ruff:fix`, `task mypy`, `task test`, `task ci`.

### 7. Links

- Business Logic Spec (docs/business-logic.md)
- Contributing (CONTRIBUTING.md)

## Side Effects

- New file: `CONTRIBUTING.md` (extracted from current README's Contributing section + CLAUDE.md conventions)
- Existing `README.md` replaced entirely
