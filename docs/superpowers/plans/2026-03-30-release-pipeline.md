# Release Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automated release pipeline via GitHub Actions — build Docker images, push to ghcr.io, manage versions, update compose files, and create GitHub Releases.

**Architecture:** Two `workflow_dispatch` workflows (minor + patch) sharing a composite action for build/push/release. Version source of truth is `pyproject.toml`. Release branches (`release/X.Y`) are long-lived, `main` always reflects the latest version.

**Tech Stack:** GitHub Actions, Docker Buildx, ghcr.io, `gh` CLI, shell scripting

**Spec:** `docs/superpowers/specs/2026-03-30-release-pipeline-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `.github/actions/publish-release/action.yml` | Create | Composite action: Docker build+push, GitHub Release |
| `.github/workflows/release-minor.yml` | Create | Minor release orchestration from `main` |
| `.github/workflows/release-patch.yml` | Create | Patch release orchestration from `release/*` |
| `Taskfile.yml` | Modify | Remove `VERSION` var, `build` task, `deploy` task |
| `README.md` | Modify | Add version badge, update Docker/commands sections |

---

### Task 1: Create composite action

**Files:**
- Create: `.github/actions/publish-release/action.yml`

- [ ] **Step 1: Create the action directory**

```bash
mkdir -p .github/actions/publish-release
```

- [ ] **Step 2: Write the composite action**

Create `.github/actions/publish-release/action.yml`:

```yaml
name: Publish Release
description: Build Docker image, push to ghcr.io, create GitHub Release

inputs:
  version:
    description: Version string (e.g., 0.2.0)
    required: true
  image_name:
    description: Full ghcr.io image name (e.g., ghcr.io/owner/rental-platform)
    required: true
  github_token:
    description: GitHub token for registry auth and release creation
    required: true
  is_latest:
    description: Whether to mark the GitHub Release as "latest"
    required: true
    default: "true"

runs:
  using: composite
  steps:
    - name: Set up Docker Buildx
      uses: docker/setup-buildx-action@v3

    - name: Log in to ghcr.io
      uses: docker/login-action@v3
      with:
        registry: ghcr.io
        username: ${{ github.actor }}
        password: ${{ inputs.github_token }}

    - name: Build and push Docker image
      uses: docker/build-push-action@v6
      with:
        context: .
        push: true
        tags: ${{ inputs.image_name }}:${{ inputs.version }}
        build-args: APP_VERSION=${{ inputs.version }}

    - name: Create GitHub Release
      shell: bash
      env:
        GH_TOKEN: ${{ inputs.github_token }}
      run: |
        if [ "${{ inputs.is_latest }}" = "true" ]; then
          LATEST_FLAG="--latest"
        else
          LATEST_FLAG="--latest=false"
        fi

        PREV_TAG=$(git tag --sort=-v:refname | grep -v "^v${{ inputs.version }}$" | head -1)

        if [ -n "$PREV_TAG" ]; then
          gh release create "v${{ inputs.version }}" \
            --title "v${{ inputs.version }}" \
            --generate-notes \
            --notes-start-tag "$PREV_TAG" \
            $LATEST_FLAG
        else
          gh release create "v${{ inputs.version }}" \
            --title "v${{ inputs.version }}" \
            --generate-notes \
            $LATEST_FLAG
        fi
```

- [ ] **Step 3: Validate YAML syntax**

```bash
python -c "import yaml; yaml.safe_load(open('.github/actions/publish-release/action.yml'))"
```

Expected: no output (valid YAML).

- [ ] **Step 4: Commit**

```bash
git add .github/actions/publish-release/action.yml
git commit -m "ci: add publish-release composite action"
```

---

### Task 2: Create release-minor workflow

**Files:**
- Create: `.github/workflows/release-minor.yml`

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/release-minor.yml`:

```yaml
name: release-minor

on:
  workflow_dispatch:

permissions:
  contents: write
  packages: write

jobs:
  release:
    runs-on: ubuntu-latest
    if: github.ref_name == 'main'
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0

      - name: Compute next minor version
        id: version
        run: |
          CURRENT=$(grep -m1 '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
          IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"
          NEW_VERSION="${MAJOR}.$((MINOR + 1)).0"
          RELEASE_BRANCH="release/${MAJOR}.$((MINOR + 1))"
          echo "current=$CURRENT" >> "$GITHUB_OUTPUT"
          echo "version=$NEW_VERSION" >> "$GITHUB_OUTPUT"
          echo "branch=$RELEASE_BRANCH" >> "$GITHUB_OUTPUT"
          echo "Bumping $CURRENT → $NEW_VERSION"

      - name: Configure git
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

      - name: Bump version in pyproject.toml
        run: |
          sed -i 's/^version = ".*"/version = "${{ steps.version.outputs.version }}"/' pyproject.toml
          git add pyproject.toml
          git commit -m "chore: bump version to ${{ steps.version.outputs.version }}"

      - name: Create release branch and tag
        run: |
          git branch "${{ steps.version.outputs.branch }}"
          git tag "v${{ steps.version.outputs.version }}"

      - name: Push main, release branch, and tag
        run: |
          git push origin main
          git push origin "${{ steps.version.outputs.branch }}"
          git push origin "v${{ steps.version.outputs.version }}"

      - name: Build, push, and create release
        uses: ./.github/actions/publish-release
        with:
          version: ${{ steps.version.outputs.version }}
          image_name: ghcr.io/${{ github.repository_owner }}/rental-platform
          github_token: ${{ secrets.GITHUB_TOKEN }}
          is_latest: "true"

      - name: Pin image in docker-compose.prod.yml on release branch
        run: |
          git checkout "${{ steps.version.outputs.branch }}"
          IMAGE="ghcr.io/${{ github.repository_owner }}/rental-platform:${{ steps.version.outputs.version }}"
          sed -i "s|image: .*rental-platform.*|image: ${IMAGE}|" docker-compose.prod.yml
          git add docker-compose.prod.yml
          git commit -m "chore: pin image to ${{ steps.version.outputs.version }}"
          git push origin "${{ steps.version.outputs.branch }}"

      - name: Update README badge on main
        run: |
          git checkout main
          VERSION="${{ steps.version.outputs.version }}"
          sed -i "s|version-[0-9.]*-blue|version-${VERSION}-blue|" README.md
          if ! git diff --quiet README.md; then
            git add README.md
            git commit -m "chore: update version badge to ${VERSION}"
            git push origin main
          fi
```

- [ ] **Step 2: Validate YAML syntax**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/release-minor.yml'))"
```

Expected: no output (valid YAML).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release-minor.yml
git commit -m "ci: add minor release workflow"
```

---

### Task 3: Create release-patch workflow

**Files:**
- Create: `.github/workflows/release-patch.yml`

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/release-patch.yml`:

```yaml
name: release-patch

on:
  workflow_dispatch:

permissions:
  contents: write
  packages: write

jobs:
  release:
    runs-on: ubuntu-latest
    if: startsWith(github.ref_name, 'release/')
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0

      - name: Compute next patch version
        id: version
        run: |
          CURRENT=$(grep -m1 '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
          IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"
          NEW_VERSION="${MAJOR}.${MINOR}.$((PATCH + 1))"
          echo "current=$CURRENT" >> "$GITHUB_OUTPUT"
          echo "version=$NEW_VERSION" >> "$GITHUB_OUTPUT"
          echo "major=$MAJOR" >> "$GITHUB_OUTPUT"
          echo "minor=$MINOR" >> "$GITHUB_OUTPUT"
          echo "Bumping $CURRENT → $NEW_VERSION"

      - name: Configure git
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

      - name: Bump version and tag
        run: |
          sed -i 's/^version = ".*"/version = "${{ steps.version.outputs.version }}"/' pyproject.toml
          git add pyproject.toml
          git commit -m "chore: bump version to ${{ steps.version.outputs.version }}"
          git tag "v${{ steps.version.outputs.version }}"

      - name: Push branch and tag
        run: |
          git push origin "${{ github.ref_name }}"
          git push origin "v${{ steps.version.outputs.version }}"

      - name: Determine if latest minor
        id: check_latest
        run: |
          CURRENT_MINOR="${{ steps.version.outputs.major }}.${{ steps.version.outputs.minor }}"
          LATEST_MINOR=$(git branch -r --list 'origin/release/*' | sed 's|.*release/||' | sort -t. -k1,1n -k2,2n | tail -1)
          IS_LATEST="false"
          if [ "$CURRENT_MINOR" = "$LATEST_MINOR" ]; then
            IS_LATEST="true"
          fi
          echo "is_latest=$IS_LATEST" >> "$GITHUB_OUTPUT"
          echo "Current minor: $CURRENT_MINOR, latest minor: $LATEST_MINOR, is_latest: $IS_LATEST"

      - name: Build, push, and create release
        uses: ./.github/actions/publish-release
        with:
          version: ${{ steps.version.outputs.version }}
          image_name: ghcr.io/${{ github.repository_owner }}/rental-platform
          github_token: ${{ secrets.GITHUB_TOKEN }}
          is_latest: ${{ steps.check_latest.outputs.is_latest }}

      - name: Pin image in docker-compose.prod.yml
        run: |
          IMAGE="ghcr.io/${{ github.repository_owner }}/rental-platform:${{ steps.version.outputs.version }}"
          sed -i "s|image: .*rental-platform.*|image: ${IMAGE}|" docker-compose.prod.yml
          git add docker-compose.prod.yml
          git commit -m "chore: pin image to ${{ steps.version.outputs.version }}"
          git push origin "${{ github.ref_name }}"

      - name: Update main if latest minor
        if: steps.check_latest.outputs.is_latest == 'true'
        run: |
          VERSION="${{ steps.version.outputs.version }}"
          git fetch origin main
          git checkout main
          sed -i 's/^version = ".*"/version = "'"${VERSION}"'"/' pyproject.toml
          sed -i "s|version-[0-9.]*-blue|version-${VERSION}-blue|" README.md
          git add pyproject.toml README.md
          git commit -m "chore: sync version to ${VERSION} from patch release"
          git push origin main
```

- [ ] **Step 2: Validate YAML syntax**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/release-patch.yml'))"
```

Expected: no output (valid YAML).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release-patch.yml
git commit -m "ci: add patch release workflow"
```

---

### Task 4: Clean up Taskfile

**Files:**
- Modify: `Taskfile.yml:1-2` (remove `VERSION` var)
- Modify: `Taskfile.yml:109-121` (remove `build` and `deploy` tasks)

- [ ] **Step 1: Remove VERSION variable**

In `Taskfile.yml`, change the `vars` block from:

```yaml
vars:
  IMAGE_NAME: rental-platform
  VERSION: dev
```

to:

```yaml
vars:
  IMAGE_NAME: rental-platform
```

- [ ] **Step 2: Remove build and deploy tasks**

Delete lines 109-121 from `Taskfile.yml` (the entire `# ── Build & Deploy` section):

```yaml
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
```

- [ ] **Step 3: Verify Taskfile is valid**

```bash
task --list
```

Expected: lists all remaining tasks (setup, infra:*, test:*, run, lint, lint:fix, typecheck, test, test:cov, test:lf, db:*, ci). No `build` or `deploy`.

- [ ] **Step 4: Commit**

```bash
git add Taskfile.yml
git commit -m "chore: remove build/deploy tasks from Taskfile"
```

---

### Task 5: Update README

**Files:**
- Modify: `README.md:1-4` (add version badge)
- Modify: `README.md:104-108` (remove build/deploy from commands table)
- Modify: `README.md:168-176` (update production Docker section)

- [ ] **Step 1: Add version badge**

In `README.md`, after the existing badges on lines 3-4, add the version badge. The badge block becomes:

```markdown
[![tests](https://github.com/khamitovdr/equipment-sharing-backend-v2/actions/workflows/coverage.yml/badge.svg)](https://github.com/khamitovdr/equipment-sharing-backend-v2/actions/workflows/coverage.yml)
[![coverage](https://coveralls.io/repos/github/khamitovdr/equipment-sharing-backend-v2/badge.svg?branch=main)](https://coveralls.io/github/khamitovdr/equipment-sharing-backend-v2?branch=main)
[![version](https://img.shields.io/badge/version-0.1.0-blue)](https://github.com/khamitovdr/equipment-sharing-backend-v2/pkgs/container/rental-platform)
```

- [ ] **Step 2: Remove build/deploy from commands table**

Remove these two rows from the Development Commands table:

```markdown
| `task build VERSION=1.2.3` | Build tagged production Docker image |
| `task deploy VERSION=1.2.3` | Build + deploy to production |
```

And remove the `| **Build & Deploy** | |` header row above them.

- [ ] **Step 3: Update production Docker section**

Replace the Production section (lines 168-176):

```markdown
### Production

Full stack in Docker — PostgreSQL + app (gunicorn with uvicorn workers):

```bash
task build VERSION=1.2.3    # build image with version tag
task deploy VERSION=1.2.3   # build + start production stack
```

Uses `docker-compose.prod.yml`. Secrets are passed via environment variables to the container.
```

with:

```markdown
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
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add version badge and update release docs"
```

---

### Task 6: Final validation

- [ ] **Step 1: Validate all workflow YAML files**

```bash
python -c "
import yaml, pathlib
for f in sorted(pathlib.Path('.github').rglob('*.yml')):
    try:
        yaml.safe_load(f.read_text())
        print(f'OK: {f}')
    except yaml.YAMLError as e:
        print(f'FAIL: {f}: {e}')
"
```

Expected: all files print `OK`.

- [ ] **Step 2: Verify sed patterns match current files**

Test the version bump sed pattern against `pyproject.toml`:

```bash
grep -m1 '^version = ' pyproject.toml
```

Expected: `version = "0.1.0"` — confirms the sed pattern `^version = ".*"` will match.

Test the image sed pattern against `docker-compose.prod.yml`:

```bash
grep 'rental-platform' docker-compose.prod.yml
```

Expected: two lines with `image: rental-platform:${APP_VERSION:-latest}` — confirms `image: .*rental-platform.*` will match both.

Test the badge sed pattern (will work once badge is added):

```bash
grep 'version-.*-blue' README.md
```

Expected: one line with the badge — confirms `version-[0-9.]*-blue` will match.

- [ ] **Step 3: Run lint to check nothing is broken**

```bash
task lint
```

Expected: passes (no Python files changed, but good to confirm repo integrity).
