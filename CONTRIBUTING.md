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
