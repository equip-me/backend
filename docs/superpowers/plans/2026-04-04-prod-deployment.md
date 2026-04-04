# Production Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a fully-functional production deployment system with TLS reverse proxy, automated setup from a developer machine, and a one-command redeployment script.

**Architecture:** A `deploy/` directory in the repo contains docker-compose, config files, and shell scripts. `setup.sh` runs locally, prompts for config, generates a `dist/` directory with secrets, and SCPs everything to the VM. nginx-proxy + acme-companion handle TLS and routing to 3 subdomains (api, grafana, s3). A code change adds `presigned_endpoint_url` so MinIO presigned URLs point to the public S3 subdomain.

**Tech Stack:** Docker Compose, nginx-proxy, acme-companion, bash scripts, go-task

**Spec:** `docs/superpowers/specs/2026-04-04-prod-deployment-design.md`

---

## File Map

### New files

| File | Responsibility |
|------|---------------|
| `deploy/docker-compose.prod.yml` | Production stack: 10 services, two networks, nginx-proxy TLS |
| `deploy/setup.sh` | Interactive setup: prompts, generates dist/, SCPs to VM, starts stack |
| `deploy/deploy.sh` | Redeploy: updates version, SSHes to VM, restarts app+worker |
| `deploy/config/otel-collector.yaml` | OTel collector config for prod (copy of existing) |
| `deploy/config/grafana/provisioning/datasources/clickhouse.yaml` | Grafana ClickHouse datasource |
| `deploy/config/grafana/provisioning/dashboards/default.yaml` | Grafana dashboard provisioning |
| `deploy/config/grafana/dashboards/*.json` | 4 Grafana dashboard JSON files (copied from config/) |
| `tests/unit/test_presigned_url.py` | Tests for presigned URL rewriting in StorageClient |

### Modified files

| File | Change |
|------|--------|
| `app/core/config.py:42-47` | Add `presigned_endpoint_url` field to `StorageSettings` |
| `config/base.yaml:32-35` | Add `presigned_endpoint_url` to storage section |
| `app/media/storage.py:11-25,47-63` | Accept and use `presigned_endpoint_url` in constructor and URL generation |
| `app/main.py:53-58` | Pass `presigned_endpoint_url` to `init_storage()` |
| `tests/unit/test_storage_singleton.py:17-30` | Update `init_storage` calls with new parameter |
| `Taskfile.yml` | Add `prod:setup` and `prod:deploy` tasks |
| `docker-compose.prod.yml` | Remove (replaced by `deploy/docker-compose.prod.yml`) |
| `README.md` | Add production deployment section |
| `CLAUDE.md` | Add `prod:setup` and `prod:deploy` to key commands table |

---

## Python Conventions (for subagents)

- **No `# type: ignore`** — fix the type error or restructure
- **No `from __future__ import annotations`** — Pydantic v2 and Tortoise need runtime types
- **Strict mypy** — every function fully typed, no implicit `Any`
- **Ruff** — line length 119, `select = ["ALL"]` with specific ignores
- Lint: `poetry run ruff check . && poetry run ruff format --check .`
- Type check: `poetry run mypy .`
- Test: `poetry run pytest`

---

### Task 1: Add `presigned_endpoint_url` to config and storage

**Files:**
- Modify: `app/core/config.py:42-47`
- Modify: `config/base.yaml:32-35`
- Modify: `app/media/storage.py:11-25,47-63`
- Modify: `app/main.py:53-58`
- Modify: `tests/unit/test_storage_singleton.py:17-30`
- Create: `tests/unit/test_presigned_url.py`

- [ ] **Step 1: Write failing test for presigned URL rewriting**

Create `tests/unit/test_presigned_url.py`:

```python
import pytest

from app.media.storage import StorageClient


def test_presigned_endpoint_url_stored() -> None:
    client = StorageClient(
        endpoint_url="http://minio:9000",
        presigned_endpoint_url="https://s3.example.com",
        access_key="test",
        secret_key="test",
        bucket="test",
    )
    assert client._presigned_endpoint_url == "https://s3.example.com"


def test_presigned_endpoint_url_defaults_to_endpoint_url() -> None:
    client = StorageClient(
        endpoint_url="http://minio:9000",
        presigned_endpoint_url="",
        access_key="test",
        secret_key="test",
        bucket="test",
    )
    assert client._presigned_endpoint_url == "http://minio:9000"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/unit/test_presigned_url.py -v`
Expected: FAIL — `StorageClient.__init__() got an unexpected keyword argument 'presigned_endpoint_url'`

- [ ] **Step 3: Add `presigned_endpoint_url` to StorageSettings**

In `app/core/config.py`, change `StorageSettings`:

```python
class StorageSettings(BaseModel):
    endpoint_url: str = "http://localhost:9000"
    presigned_endpoint_url: str = ""
    bucket: str = "rental-media"
    presigned_url_expiry_seconds: int = 3600
    access_key: str = ""
    secret_key: str = ""
```

- [ ] **Step 4: Add `presigned_endpoint_url` to `config/base.yaml`**

In the `storage:` section of `config/base.yaml`, add after `endpoint_url`:

```yaml
storage:
  endpoint_url: "http://localhost:9000"
  presigned_endpoint_url: "http://localhost:9000"
  bucket: "rental-media"
```

- [ ] **Step 5: Update StorageClient constructor and URL generation**

In `app/media/storage.py`, update the `__init__` method:

```python
class StorageClient:
    def __init__(
        self,
        endpoint_url: str,
        presigned_endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._presigned_endpoint_url = presigned_endpoint_url or endpoint_url
        self._bucket = bucket
        self._session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self._config = Config(signature_version="s3v4")
```

Update `generate_upload_url`:

```python
    async def generate_upload_url(self, key: str, content_type: str, expires: int) -> str:
        async with self._session.client("s3", endpoint_url=self._endpoint_url, config=self._config) as s3:
            url: str = await s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=expires,
            )
            return url.replace(self._endpoint_url, self._presigned_endpoint_url, 1)
```

Update `generate_download_url`:

```python
    async def generate_download_url(self, key: str, expires: int) -> str:
        async with self._session.client("s3", endpoint_url=self._endpoint_url, config=self._config) as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires,
            )
            return url.replace(self._endpoint_url, self._presigned_endpoint_url, 1)
```

Update `init_storage`:

```python
def init_storage(
    endpoint_url: str,
    presigned_endpoint_url: str,
    access_key: str,
    secret_key: str,
    bucket: str,
) -> StorageClient:
    global _instance  # noqa: PLW0603
    _instance = StorageClient(
        endpoint_url=endpoint_url,
        presigned_endpoint_url=presigned_endpoint_url,
        access_key=access_key,
        secret_key=secret_key,
        bucket=bucket,
    )
    return _instance
```

- [ ] **Step 6: Update `app/main.py` to pass `presigned_endpoint_url`**

In `app/main.py`, update the `init_storage` call inside `lifespan` (around line 53):

```python
        storage = init_storage(
            endpoint_url=settings.storage.endpoint_url,
            presigned_endpoint_url=settings.storage.presigned_endpoint_url,
            access_key=settings.storage.access_key,
            secret_key=settings.storage.secret_key,
            bucket=settings.storage.bucket,
        )
```

- [ ] **Step 7: Update existing storage singleton test**

In `tests/unit/test_storage_singleton.py`, update the `test_init_storage_and_get_storage` function:

```python
def test_init_storage_and_get_storage() -> None:
    original = storage_mod._instance
    try:
        storage_mod._instance = None
        client = storage_mod.init_storage(
            endpoint_url="http://localhost:9000",
            presigned_endpoint_url="http://localhost:9000",
            access_key="test",
            secret_key="test",
            bucket="test-bucket",
        )
        assert client is not None
        assert storage_mod.get_storage() is client
        assert client.bucket == "test-bucket"
    finally:
        storage_mod._instance = original
```

- [ ] **Step 8: Run all tests and type checks**

Run: `poetry run pytest tests/unit/test_presigned_url.py tests/unit/test_storage_singleton.py -v`
Expected: All PASS

Run: `poetry run mypy app/core/config.py app/media/storage.py app/main.py`
Expected: Success

- [ ] **Step 9: Lint**

Run: `poetry run ruff check app/core/config.py app/media/storage.py app/main.py tests/unit/test_presigned_url.py tests/unit/test_storage_singleton.py`
Run: `poetry run ruff format --check app/core/config.py app/media/storage.py app/main.py tests/unit/test_presigned_url.py tests/unit/test_storage_singleton.py`
Expected: No issues

- [ ] **Step 10: Commit**

```bash
git add app/core/config.py config/base.yaml app/media/storage.py app/main.py tests/unit/test_presigned_url.py tests/unit/test_storage_singleton.py
git commit -m "feat(storage): add presigned_endpoint_url for public S3 URL rewriting"
```

---

### Task 2: Create `deploy/docker-compose.prod.yml`

**Files:**
- Create: `deploy/docker-compose.prod.yml`
- Delete: `docker-compose.prod.yml` (root level — replaced by deploy/)

- [ ] **Step 1: Create `deploy/docker-compose.prod.yml`**

```yaml
services:
  # ── Reverse proxy + TLS ────────────────────────────────
  nginx-proxy:
    image: nginxproxy/nginx-proxy:1.7
    container_name: nginx-proxy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - certs:/etc/nginx/certs:ro
      - vhost:/etc/nginx/vhost.d
      - html:/usr/share/nginx/html
      - /var/run/docker.sock:/tmp/docker.sock:ro
    networks:
      - proxy

  acme-companion:
    image: nginxproxy/acme-companion:2.5
    volumes:
      - certs:/etc/nginx/certs
      - vhost:/etc/nginx/vhost.d
      - html:/usr/share/nginx/html
      - acme:/etc/acme.sh
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      NGINX_PROXY_CONTAINER: nginx-proxy
    depends_on:
      - nginx-proxy
    networks:
      - proxy

  # ── Application ─���──────────────────────────────────────
  app:
    image: ghcr.io/khamitovdr/rental-platform:${APP_VERSION}
    environment:
      APP_ENV: prod
      DATABASE__HOST: db
      DATABASE__NAME: ${POSTGRES_DB}
      DATABASE__USER: ${POSTGRES_USER}
      DATABASE__PASSWORD: ${POSTGRES_PASSWORD}
      JWT__SECRET: ${JWT_SECRET}
      DADATA_API_KEY: ${DADATA_API_KEY:-}
      OBSERVABILITY__OTLP_ENDPOINT: otel-collector:4317
      STORAGE__ENDPOINT_URL: http://minio:9000
      STORAGE__PRESIGNED_ENDPOINT_URL: ${STORAGE__PRESIGNED_ENDPOINT_URL}
      STORAGE__ACCESS_KEY: ${MINIO_ROOT_USER}
      STORAGE__SECRET_KEY: ${MINIO_ROOT_PASSWORD}
      WORKER__REDIS_URL: redis://redis:6379
      CORS__ALLOW_ORIGINS: ${CORS__ALLOW_ORIGINS}
      VIRTUAL_HOST: ${API_HOST}
      VIRTUAL_PORT: "8000"
      LETSENCRYPT_HOST: ${API_HOST}
      LETSENCRYPT_EMAIL: ${LETSENCRYPT_EMAIL}
    depends_on:
      db:
        condition: service_started
      redis:
        condition: service_started
      minio:
        condition: service_started
      otel-collector:
        condition: service_started
    command: gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
    networks:
      - proxy
      - internal

  worker:
    image: ghcr.io/khamitovdr/rental-platform:${APP_VERSION}
    environment:
      APP_ENV: prod
      DATABASE__HOST: db
      DATABASE__NAME: ${POSTGRES_DB}
      DATABASE__USER: ${POSTGRES_USER}
      DATABASE__PASSWORD: ${POSTGRES_PASSWORD}
      STORAGE__ENDPOINT_URL: http://minio:9000
      STORAGE__ACCESS_KEY: ${MINIO_ROOT_USER}
      STORAGE__SECRET_KEY: ${MINIO_ROOT_PASSWORD}
      WORKER__REDIS_URL: redis://redis:6379
    depends_on:
      db:
        condition: service_started
      redis:
        condition: service_started
      minio:
        condition: service_started
    command: python -m app.worker
    networks:
      - internal

  # ── Data stores ──────��─────────────────────────────────
  db:
    image: postgres:17.4-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - pgdata:/var/lib/postgresql/data
    networks:
      - internal

  redis:
    image: redis:7.4-alpine
    volumes:
      - redis_data:/data
    networks:
      - internal

  minio:
    image: minio/minio:RELEASE.2025-03-12T18-04-18Z
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
      VIRTUAL_HOST: ${S3_HOST}
      VIRTUAL_PORT: "9000"
      LETSENCRYPT_HOST: ${S3_HOST}
      LETSENCRYPT_EMAIL: ${LETSENCRYPT_EMAIL}
    volumes:
      - minio_data:/data
    networks:
      - proxy
      - internal

  # ── Observability ──────────────────────────────────────
  clickhouse:
    image: clickhouse/clickhouse-server:25.3
    mem_limit: 2g
    environment:
      CLICKHOUSE_DB: otel
      CLICKHOUSE_USER: default
      CLICKHOUSE_PASSWORD: clickhouse
    volumes:
      - clickhouse_data:/var/lib/clickhouse
    healthcheck:
      test: ["CMD-SHELL", "clickhouse-client --password clickhouse --query 'SELECT 1'"]
      interval: 5s
      timeout: 3s
      retries: 10
    networks:
      - internal

  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.121.0
    command: ["--config=/etc/otelcol-contrib/config.yaml"]
    volumes:
      - ./config/otel-collector.yaml:/etc/otelcol-contrib/config.yaml:ro
    depends_on:
      clickhouse:
        condition: service_healthy
    networks:
      - internal

  grafana:
    image: grafana/grafana:11.6.0
    environment:
      GF_INSTALL_PLUGINS: grafana-clickhouse-datasource
      GF_AUTH_ANONYMOUS_ENABLED: "false"
      GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}
      VIRTUAL_HOST: ${GRAFANA_HOST}
      VIRTUAL_PORT: "3000"
      LETSENCRYPT_HOST: ${GRAFANA_HOST}
      LETSENCRYPT_EMAIL: ${LETSENCRYPT_EMAIL}
    volumes:
      - ./config/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./config/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafana_data:/var/lib/grafana
    depends_on:
      - clickhouse
    networks:
      - proxy
      - internal

volumes:
  pgdata:
  redis_data:
  minio_data:
  clickhouse_data:
  grafana_data:
  certs:
  vhost:
  html:
  acme:

networks:
  proxy:
  internal:
```

- [ ] **Step 2: Remove old root-level `docker-compose.prod.yml`**

```bash
git rm docker-compose.prod.yml
```

- [ ] **Step 3: Commit**

```bash
git add deploy/docker-compose.prod.yml
git commit -m "feat(deploy): add production docker-compose with nginx-proxy TLS"
```

---

### Task 3: Create deploy config files

**Files:**
- Create: `deploy/config/otel-collector.yaml`
- Create: `deploy/config/grafana/provisioning/datasources/clickhouse.yaml`
- Create: `deploy/config/grafana/provisioning/dashboards/default.yaml`
- Copy: `deploy/config/grafana/dashboards/*.json` (4 files from `config/grafana/dashboards/`)

- [ ] **Step 1: Create `deploy/config/otel-collector.yaml`**

Copy from `config/otel-collector-prod.yaml` (identical content):

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 5s
    send_batch_size: 1000

exporters:
  clickhouse:
    endpoint: tcp://clickhouse:9000
    username: default
    password: clickhouse
    database: otel
    create_schema: true
    ttl_days: 30
    logs_table_name: otel_logs
    traces_table_name: otel_traces
    metrics_table_name: otel_metrics

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [clickhouse]
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [clickhouse]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [clickhouse]
```

- [ ] **Step 2: Create `deploy/config/grafana/provisioning/datasources/clickhouse.yaml`**

Copy from `config/grafana/provisioning/datasources/clickhouse.yaml` (identical content):

```yaml
apiVersion: 1

datasources:
  - name: ClickHouse
    type: grafana-clickhouse-datasource
    uid: clickhouse
    access: proxy
    jsonData:
      host: clickhouse
      port: 9000
      protocol: native
      defaultDatabase: otel
      username: default
    secureJsonData:
      password: clickhouse
    isDefault: true
    editable: true
```

- [ ] **Step 3: Create `deploy/config/grafana/provisioning/dashboards/default.yaml`**

Copy from `config/grafana/provisioning/dashboards/default.yaml` (identical content):

```yaml
apiVersion: 1

providers:
  - name: default
    orgId: 1
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: true
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: false
```

- [ ] **Step 4: Copy Grafana dashboard JSON files**

```bash
mkdir -p deploy/config/grafana/dashboards
cp config/grafana/dashboards/api-overview.json deploy/config/grafana/dashboards/
cp config/grafana/dashboards/business-events.json deploy/config/grafana/dashboards/
cp config/grafana/dashboards/infrastructure.json deploy/config/grafana/dashboards/
cp config/grafana/dashboards/traces-explorer.json deploy/config/grafana/dashboards/
```

- [ ] **Step 5: Commit**

```bash
git add deploy/config/
git commit -m "feat(deploy): add otel-collector and grafana config for production"
```

---

### Task 4: Create `deploy/setup.sh`

**Files:**
- Create: `deploy/setup.sh`

- [ ] **Step 1: Create `deploy/setup.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"

# ── Colors ────���──────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Prompt helper ────���───────────────────────────────────
prompt() {
    local var_name="$1" prompt_text="$2" default="$3"
    local input
    if [[ -n "$default" ]]; then
        read -rp "$(echo -e "${CYAN}$prompt_text${NC} [${default}]: ")" input
        eval "$var_name=\"${input:-$default}\""
    else
        while true; do
            read -rp "$(echo -e "${CYAN}$prompt_text${NC}: ")" input
            if [[ -n "$input" ]]; then
                eval "$var_name=\"$input\""
                break
            fi
            error "This field is required"
        done
    fi
}

gen_secret() {
    openssl rand -base64 "$1" 2>/dev/null | tr -d '\n'
}

# ── Collect configuration ────���───────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Rental Platform — Production Setup${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""

info "Domain & access"
prompt DOMAIN        "Domain name (e.g. equip-me.ru)" ""
prompt LETSENCRYPT_EMAIL "Let's Encrypt email" ""
prompt APP_VERSION   "App version to deploy" ""
prompt VM_HOST       "VM address (user@host)" ""

echo ""
info "Database"
prompt POSTGRES_USER "PostgreSQL user" "rental"
prompt POSTGRES_DB   "PostgreSQL database" "rental"
prompt POSTGRES_PASSWORD "PostgreSQL password" "$(gen_secret 32)"

echo ""
info "Authentication"
prompt JWT_SECRET "JWT secret key" "$(gen_secret 48)"

echo ""
info "Object storage (MinIO)"
prompt MINIO_ROOT_USER     "MinIO root user" "minioadmin"
prompt MINIO_ROOT_PASSWORD "MinIO root password" "$(gen_secret 32)"

echo ""
info "Monitoring"
prompt GRAFANA_ADMIN_PASSWORD "Grafana admin password" "$(gen_secret 16)"

echo ""
info "External services"
prompt DADATA_API_KEY "Dadata API key (optional, press Enter to skip)" ""

# ── Computed values ─────��────────────────────────────────
API_HOST="api.${DOMAIN}"
GRAFANA_HOST="grafana.${DOMAIN}"
S3_HOST="s3.${DOMAIN}"
STORAGE__PRESIGNED_ENDPOINT_URL="https://${S3_HOST}"
CORS__ALLOW_ORIGINS="[\"https://${DOMAIN}\",\"https://www.${DOMAIN}\"]"

# ── Build dist/ ──────────────────────────────────────────
info "Building dist/ directory..."

rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

cp "$SCRIPT_DIR/docker-compose.prod.yml" "$DIST_DIR/"
cp -r "$SCRIPT_DIR/config" "$DIST_DIR/"

cat > "$DIST_DIR/.env" <<EOF
# Generated by setup.sh on $(date -u +"%Y-%m-%d %H:%M:%S UTC")
# Domain
DOMAIN=${DOMAIN}
API_HOST=${API_HOST}
GRAFANA_HOST=${GRAFANA_HOST}
S3_HOST=${S3_HOST}
LETSENCRYPT_EMAIL=${LETSENCRYPT_EMAIL}

# App
APP_VERSION=${APP_VERSION}

# Database
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_DB=${POSTGRES_DB}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}

# Auth
JWT_SECRET=${JWT_SECRET}

# Storage
MINIO_ROOT_USER=${MINIO_ROOT_USER}
MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}
STORAGE__PRESIGNED_ENDPOINT_URL=${STORAGE__PRESIGNED_ENDPOINT_URL}

# CORS
CORS__ALLOW_ORIGINS=${CORS__ALLOW_ORIGINS}

# Grafana
GRAFANA_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}

# External
DADATA_API_KEY=${DADATA_API_KEY}

# Deployment
VM_HOST=${VM_HOST}
EOF

ok "dist/ directory ready"

# ── Deploy to VM ─────────���───────────────────────────────
echo ""
info "Deploying to ${VM_HOST}..."

ssh "$VM_HOST" "mkdir -p ~/rental-platform"
scp -r "$DIST_DIR/." "$VM_HOST:~/rental-platform/"

ok "Files copied to ${VM_HOST}:~/rental-platform/"

info "Starting services..."
ssh "$VM_HOST" "cd ~/rental-platform && docker compose pull && docker compose up -d"

# ── Summary ──────���───────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Deployment complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo -e "  API:     ${CYAN}https://${API_HOST}${NC}"
echo -e "  Grafana: ${CYAN}https://${GRAFANA_HOST}${NC}"
echo -e "  S3:      ${CYAN}https://${S3_HOST}${NC}"
echo ""
echo -e "  Grafana login: admin / ${GRAFANA_ADMIN_PASSWORD}"
echo ""
info "TLS certificates will be provisioned automatically by Let's Encrypt."
info "Ensure DNS A records point to the VM for: ${API_HOST}, ${GRAFANA_HOST}, ${S3_HOST}"
echo ""
```

- [ ] **Step 2: Make executable**

```bash
chmod +x deploy/setup.sh
```

- [ ] **Step 3: Commit**

```bash
git add deploy/setup.sh
git commit -m "feat(deploy): add interactive setup script for VM provisioning"
```

---

### Task 5: Create `deploy/deploy.sh`

**Files:**
- Create: `deploy/deploy.sh`

- [ ] **Step 1: Create `deploy/deploy.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
ENV_FILE="$DIST_DIR/.env"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Validate arguments ───��───────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <version>"
    echo "Example: $0 0.5.0"
    exit 1
fi

VERSION="$1"

if [[ ! -f "$ENV_FILE" ]]; then
    error "dist/.env not found. Run setup.sh first."
fi

# ── Read VM_HOST from .env ───────────────────────────────
VM_HOST=$(grep '^VM_HOST=' "$ENV_FILE" | cut -d'=' -f2-)
if [[ -z "$VM_HOST" ]]; then
    error "VM_HOST not found in dist/.env"
fi

# ── Update version ───────────���───────────────────────────
info "Updating APP_VERSION to ${VERSION}..."
sed -i.bak "s/^APP_VERSION=.*/APP_VERSION=${VERSION}/" "$ENV_FILE"
rm -f "$ENV_FILE.bak"

# ── Deploy ─────���─────────────────────────────────────────
info "Deploying v${VERSION} to ${VM_HOST}..."

scp "$ENV_FILE" "$VM_HOST:~/rental-platform/.env"
ssh "$VM_HOST" "cd ~/rental-platform && docker compose pull app worker && docker compose up -d app worker"

ok "Deployed v${VERSION}"
info "Run 'ssh ${VM_HOST} \"cd ~/rental-platform && docker compose ps\"' to check status."
```

- [ ] **Step 2: Make executable**

```bash
chmod +x deploy/deploy.sh
```

- [ ] **Step 3: Commit**

```bash
git add deploy/deploy.sh
git commit -m "feat(deploy): add version deployment script"
```

---

### Task 6: Add Taskfile tasks

**Files:**
- Modify: `Taskfile.yml`

- [ ] **Step 1: Add prod tasks to Taskfile.yml**

Append before the closing of the file, after the `ci` task:

```yaml
  # ── Production deployment ─────────────────────────────
  prod:setup:
    desc: Provision a fresh VM with the production stack
    cmds:
      - ./deploy/setup.sh

  prod:deploy:
    desc: "Deploy a new app version (usage: task prod:deploy -- 0.5.0)"
    cmds:
      - ./deploy/deploy.sh {{.CLI_ARGS}}
```

- [ ] **Step 2: Verify tasks are registered**

Run: `task --list`
Expected: Should show `prod:setup` and `prod:deploy` in the list.

- [ ] **Step 3: Commit**

```bash
git add Taskfile.yml
git commit -m "feat(deploy): add prod:setup and prod:deploy Taskfile tasks"
```

---

### Task 7: Update documentation

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add production deployment section to README.md**

After the "Releases" section (line 91) and before "## Links", add:

```markdown
## Production Deployment

Deploy the full stack to a single VM with automatic TLS via Let's Encrypt.

### Prerequisites

- A VM with Docker Compose installed (Ubuntu/Debian)
- A domain with DNS A records pointing to the VM for three subdomains:
  - `api.<domain>` — API server
  - `grafana.<domain>` — Observability dashboards
  - `s3.<domain>` — Object storage (presigned URLs)
- SSH access to the VM from your machine

### First-time setup

```bash
task prod:setup
```

The script prompts for your domain, VM address, and secrets (auto-generates passwords by default). It builds a `dist/` directory, copies it to the VM, and starts all services.

### Deploying a new version

```bash
task prod:deploy -- 0.5.0
```

Updates the app version, pulls the new image on the VM, and restarts only the app and worker containers. Infrastructure stays up.
```

- [ ] **Step 2: Add prod commands to CLAUDE.md key commands table**

In the `CLAUDE.md` key commands table, add two rows:

```markdown
| `task prod:setup` | Provision fresh VM with production stack |
| `task prod:deploy -- <version>` | Deploy new app version to production |
```

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: add production deployment instructions"
```

---

### Task 8: Run full validation

- [ ] **Step 1: Run linter**

Run: `task ruff:fix`
Expected: No errors or auto-fixed cleanly.

- [ ] **Step 2: Run type checker**

Run: `task mypy`
Expected: Success, no errors.

- [ ] **Step 3: Run test suite**

Run: `task test`
Expected: All tests pass, including new `test_presigned_url.py` tests.

- [ ] **Step 4: Fix any issues found and commit**

If any issues are found, fix and commit:
```bash
git commit -m "fix: address lint/type/test issues from prod deployment changes"
```
