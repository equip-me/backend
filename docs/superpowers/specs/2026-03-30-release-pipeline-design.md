# Release Pipeline Design

GitHub Actions release pipeline with Docker image builds, ghcr.io registry, and automated version management.

## Versioning Model

**Semantic versioning** (`X.Y.Z`). Single source of truth: `version` field in `pyproject.toml`.

**Branches**:
- `main` — development trunk, version always reflects the latest release (latest minor, latest patch of that minor)
- `release/X.Y` — long-lived release branch per minor version

**Tags**: `vX.Y.Z` on each release commit (e.g., `v0.2.0`, `v0.2.1`).

**Registry**: `ghcr.io/khamitovdr/rental-platform`

## Release Flows

### Minor Release (from `main`)

Trigger: `workflow_dispatch` on `main`.

1. **Branch guard**: fail if `github.ref_name != 'main'`
2. Checkout `main`
3. Read current version from `pyproject.toml` (e.g., `0.1.3`), compute next minor (`0.2.0`)
4. Update `pyproject.toml` version to `0.2.0`, commit to `main`
5. Create branch `release/0.2` from that commit
6. Tag `v0.2.0` on that commit
7. Push `main`, `release/0.2`, and tag `v0.2.0`
8. **Composite action**: build Docker image tagged `0.2.0`, push to ghcr.io, create GitHub Release with auto-generated notes
9. Update `docker-compose.prod.yml` on `release/0.2`: pin `image: ghcr.io/khamitovdr/rental-platform:0.2.0` for both `app` and `worker` services. Commit + push to `release/0.2`
10. Update README badge on `main` with version `0.2.0`. Commit + push to `main`

### Patch Release (from `release/X.Y`)

Prerequisite: you cherry-pick commits onto the `release/X.Y` branch manually.

Trigger: `workflow_dispatch` on `release/X.Y`.

1. **Branch guard**: fail if `github.ref_name` doesn't match `release/*`
2. Checkout the `release/X.Y` branch
3. Read current version from `pyproject.toml` (e.g., `0.2.0`), bump patch (`0.2.1`)
4. Update `pyproject.toml`, commit to `release/X.Y`
5. Tag `v0.2.1`
6. Push branch + tag
7. **Composite action**: build Docker image tagged `0.2.1`, push to ghcr.io, create GitHub Release with auto-generated notes
8. Update `docker-compose.prod.yml` on `release/X.Y`: pin image to `0.2.1`. Commit + push
9. Determine if this is the **latest minor** (compare `X.Y` against all `release/*` branches). If yes:
   - Update `pyproject.toml` on `main` to `0.2.1`
   - Update README badge on `main` to `0.2.1`
   - Commit + push to `main`

## Composite Action: `.github/actions/publish-release/action.yml`

Shared build-and-publish logic used by both workflows.

### Inputs

| Input | Description |
|-------|-------------|
| `version` | Version string (e.g., `0.2.0`) |
| `image_name` | Full image name: `ghcr.io/khamitovdr/rental-platform` |
| `github_token` | `GITHUB_TOKEN` passed from the calling workflow (composite actions can't access secrets directly) |
| `is_latest` | Boolean. Whether to mark the GitHub Release as "latest". The calling workflow determines this (minor release: always true; patch release: true only if patching the latest minor) |

### Steps

1. Set up Docker Buildx
2. Log in to ghcr.io using `github_token` input
3. Build Docker image with `APP_VERSION` build arg, tag as `<image_name>:<version>`
4. Push to ghcr.io
5. Generate release notes from commits since previous tag, grouped by Conventional Commit type (feat, fix, refactor, etc.). For the first-ever release, include all commits.
6. Create GitHub Release for tag `v<version>` with generated notes. Mark as "latest" based on `is_latest` input

### Not in the composite action

These differ per workflow and stay in the orchestrating workflow:
- Branch validation
- Version bump in `pyproject.toml`
- Tag creation and pushing
- `docker-compose.prod.yml` update
- `main` branch updates (badge, version sync)

## Workflow Permissions

```yaml
permissions:
  contents: write   # commits, tags, branches
  packages: write   # ghcr.io push
```

Auth to ghcr.io via `GITHUB_TOKEN` — no extra secrets needed.

Git commits authored by `github-actions[bot]`.

## README Badge

Static shield badge at the top of `README.md`:

```markdown
[![version](https://img.shields.io/badge/version-0.2.0-blue)](https://github.com/khamitovdr/equipment-sharing-backend-v2/pkgs/container/rental-platform)
```

Updated by workflows whenever `main`'s version changes. Static badge (no external service query) because the source of truth is `pyproject.toml` on `main` and we commit there directly.

## docker-compose.prod.yml Changes

Current state uses `${APP_VERSION:-latest}`:

```yaml
app:
  image: rental-platform:${APP_VERSION:-latest}
worker:
  image: rental-platform:${APP_VERSION:-latest}
```

After release, pinned to exact ghcr.io image:

```yaml
app:
  image: ghcr.io/khamitovdr/rental-platform:0.2.0
worker:
  image: ghcr.io/khamitovdr/rental-platform:0.2.0
```

Both `app` and `worker` use the same image (different `command`).

## Taskfile Cleanup

Remove from `Taskfile.yml`:
- `VERSION` variable
- `build` task
- `deploy` task

All other tasks (setup, run, lint, test, db, infra, ci) remain unchanged.

## README Section Updates

Remove from `README.md`:
- "Build & Deploy" rows from the Development Commands table (`task build`, `task deploy`)
- Production Docker section referencing `task build` and `task deploy`

Replace with a note that releases are managed via GitHub Actions workflows.

## File Summary

| File | Action |
|------|--------|
| `.github/actions/publish-release/action.yml` | Create (composite action) |
| `.github/workflows/release-minor.yml` | Create |
| `.github/workflows/release-patch.yml` | Create |
| `docker-compose.prod.yml` | Modify (updated by workflows at release time) |
| `Taskfile.yml` | Modify (remove build/deploy tasks, VERSION var) |
| `README.md` | Modify (add version badge, update Docker/commands sections) |
