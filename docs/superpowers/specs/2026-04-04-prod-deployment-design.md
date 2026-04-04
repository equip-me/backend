# Production Deployment Design

Single-VM production deployment with TLS, reverse proxy, and one-command setup from a developer machine.

## Overview

A `deploy/` directory in the repo contains everything needed to provision a fresh Ubuntu/Debian VM running the full stack behind nginx-proxy with automatic Let's Encrypt TLS. Scripts run locally on the developer machine — nothing is cloned on the VM.

## Architecture

### Network topology

```
Internet
  │
  ├─ :80  ──► nginx-proxy ──► (redirect to 443)
  └─ :443 ──► nginx-proxy
                 ├─ api.DOMAIN     ──► app:8000
                 ├─ grafana.DOMAIN ──► grafana:3000
                 └─ s3.DOMAIN      ──► minio:9000
```

Two Docker networks:
- **proxy** — nginx-proxy, app, grafana, minio (services that need external routing)
- **internal** — all backend services (db, redis, clickhouse, otel-collector, app, worker, minio)

App, worker, and minio bridge both networks.

### Services (10 total)

| Service | Image | Network | Exposed |
|---------|-------|---------|---------|
| nginx-proxy | `nginxproxy/nginx-proxy:1.7` | proxy | 80, 443 |
| acme-companion | `nginxproxy/acme-companion:2.5` | proxy | — |
| app | `ghcr.io/khamitovdr/rental-platform:${APP_VERSION}` | proxy, internal | via nginx-proxy |
| worker | `ghcr.io/khamitovdr/rental-platform:${APP_VERSION}` | internal | — |
| db | `postgres:17.4-alpine` | internal | — |
| redis | `redis:7.4-alpine` | internal | — |
| minio | `minio/minio:RELEASE.2025-03-12T18-04-18Z` | proxy, internal | via nginx-proxy |
| clickhouse | `clickhouse/clickhouse-server:25.3` | internal | — |
| otel-collector | `otel/opentelemetry-collector-contrib:0.121.0` | internal | — |
| grafana | `grafana/grafana:11.6.0` | proxy, internal | via nginx-proxy |

### Volumes

Named volumes for all persistent data: `pgdata`, `minio_data`, `redis_data`, `clickhouse_data`, `grafana_data`, plus nginx-proxy volumes for certs/vhost/html.

## Directory structure

### In the repo

```
deploy/
  docker-compose.prod.yml
  setup.sh
  deploy.sh
  config/
    otel-collector.yaml
    grafana/
      provisioning/
        datasources/clickhouse.yaml
        dashboards/default.yaml
      dashboards/
        api-overview.json
        business-events.json
        infrastructure.json
        traces-explorer.json
```

### Generated output (gitignored)

```
dist/
  docker-compose.prod.yml
  .env
  config/
    otel-collector.yaml
    grafana/
      provisioning/...
      dashboards/...
```

`dist/` is added to `.gitignore`. It contains secrets and is ephemeral.

## setup.sh

Runs locally from the repo root (or via `task prod:setup`).

### Interactive prompts

| Prompt | Default | Notes |
|--------|---------|-------|
| Domain | (required) | e.g. `equip-me.ru` |
| Let's Encrypt email | (required) | For certificate notifications |
| App version | (required) | e.g. `0.4.0` |
| VM address | (required) | e.g. `root@123.45.67.89` |
| POSTGRES_USER | `rental` | |
| POSTGRES_DB | `rental` | |
| POSTGRES_PASSWORD | auto: `openssl rand -base64 32` | |
| JWT_SECRET | auto: `openssl rand -base64 48` | |
| MINIO_ROOT_USER | `minioadmin` | |
| MINIO_ROOT_PASSWORD | auto: `openssl rand -base64 32` | |
| GRAFANA_ADMIN_PASSWORD | auto: `openssl rand -base64 16` | |
| DADATA_API_KEY | empty | Optional |

### Steps

1. Prompt for all values, display auto-generated defaults (user can accept or override).
2. Create `dist/` directory at repo root.
3. Copy `deploy/docker-compose.prod.yml` and `deploy/config/` into `dist/`.
4. Generate `dist/.env` with all values plus computed ones:
   - `APP_VERSION=<version>`
   - `DOMAIN=<domain>`
   - `VM_HOST=<user@host>`
   - `API_HOST=api.${DOMAIN}`
   - `GRAFANA_HOST=grafana.${DOMAIN}`
   - `S3_HOST=s3.${DOMAIN}`
   - `LETSENCRYPT_EMAIL=<email>`
   - `STORAGE__PRESIGNED_ENDPOINT_URL=https://s3.${DOMAIN}`
   - `CORS__ALLOW_ORIGINS=["https://${DOMAIN}","https://www.${DOMAIN}"]` (JSON list for pydantic-settings)
   - All secrets from prompts
5. `ssh ${VM_HOST} "mkdir -p ~/rental-platform"` then `scp -r dist/. ${VM_HOST}:~/rental-platform/` (using `/.` to include dotfiles like `.env`)
6. `ssh ${VM_HOST} "cd ~/rental-platform && docker compose pull && docker compose up -d"`
7. Print summary: service URLs, generated credentials reminder, health check hints.

## deploy.sh

Runs locally (or via `task prod:deploy -- <version>`).

```
Usage: ./deploy.sh <version>
```

1. Reads `VM_HOST` and current state from `dist/.env`.
2. Updates `APP_VERSION` in `dist/.env`.
3. `scp dist/.env ${VM_HOST}:~/rental-platform/.env`
4. `ssh ${VM_HOST} "cd ~/rental-platform && docker compose pull app worker && docker compose up -d app worker"`
5. Prints status.

Only the app and worker containers restart. Infrastructure stays up.

## Taskfile integration

```yaml
prod:setup:
  desc: "Provision a fresh VM with the production stack"
  cmds:
    - ./deploy/setup.sh

prod:deploy:
  desc: "Deploy a new app version to production"
  cmds:
    - ./deploy/deploy.sh {{.CLI_ARGS}}
```

## docker-compose.prod.yml details

### nginx-proxy + acme-companion

nginx-proxy auto-discovers backend services via the Docker socket. Services declare their routing with environment variables:

```yaml
environment:
  VIRTUAL_HOST: api.${DOMAIN}
  VIRTUAL_PORT: "8000"
  LETSENCRYPT_HOST: api.${DOMAIN}
  LETSENCRYPT_EMAIL: ${LETSENCRYPT_EMAIL}
```

acme-companion watches for `LETSENCRYPT_HOST` and automatically provisions/renews TLS certificates.

WebSocket support works out of the box with nginx-proxy — no extra configuration needed for the chat endpoint.

### App service

- `APP_ENV=prod` selects `config/prod.yaml` overlay.
- Secrets passed via env vars: `DATABASE__PASSWORD`, `JWT__SECRET`, `STORAGE__ACCESS_KEY`, `STORAGE__SECRET_KEY`, `STORAGE__PRESIGNED_ENDPOINT_URL`.
- `CORS__ALLOW_ORIGINS` env var (JSON list) overrides the hardcoded `prod.yaml` origins (derived from domain at setup time).
- Depends on db, redis, otel-collector, minio.
- Command: `gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000`

### Worker service

- Same image as app, different command: `python -m app.worker`.
- Needs db, redis, minio (no otel-collector dependency).

### MinIO

- `VIRTUAL_HOST=s3.${DOMAIN}` routes traffic through nginx-proxy.
- Internal operations (app/worker uploading/downloading) use `http://minio:9000` via the internal network.
- Presigned URLs use `https://s3.${DOMAIN}` so clients can reach MinIO through the proxy.

### ClickHouse

- Internal-only, no external exposure.
- Password kept as simple default (`clickhouse`) since the service is not accessible from outside.
- 2GB memory limit.
- Healthcheck for dependent services (otel-collector).

### Observability

- otel-collector config and grafana provisioning files are mounted from `config/`.
- ClickHouse password in otel-collector.yaml and grafana datasource stays hardcoded (internal service).

## Code change: presigned_endpoint_url

### StorageSettings (app/core/config.py)

Add field:
```python
class StorageSettings(BaseModel):
    endpoint_url: str = "http://localhost:9000"
    presigned_endpoint_url: str = ""  # NEW — falls back to endpoint_url if empty
    bucket: str = "rental-media"
    presigned_url_expiry_seconds: int = 3600
    access_key: str = ""
    secret_key: str = ""
```

### config/base.yaml

Add:
```yaml
storage:
  endpoint_url: "http://localhost:9000"
  presigned_endpoint_url: "http://localhost:9000"
```

In prod, `STORAGE__PRESIGNED_ENDPOINT_URL=https://s3.${DOMAIN}` overrides this.

### StorageClient (app/media/storage.py)

- Constructor accepts `presigned_endpoint_url` parameter.
- `generate_upload_url` and `generate_download_url` replace `self._endpoint_url` with `self._presigned_endpoint_url` in the generated URL string.
- All other methods (upload, download, delete, etc.) continue using `self._endpoint_url` for internal operations.

### init_storage (app/main.py)

Pass `presigned_endpoint_url` from settings to `init_storage()`.

## CORS origins handling

Currently `prod.yaml` hardcodes:
```yaml
cors:
  allow_origins:
    - "https://equip-me.ru"
    - "https://www.equip-me.ru"
```

For the deployment setup, CORS origins are derived from the domain entered during setup and passed as `CORS__ALLOW_ORIGINS` env var (JSON list format supported by pydantic-settings, e.g. `'["https://equip-me.ru","https://www.equip-me.ru"]'`). This way `prod.yaml` serves as a fallback default, but the actual domain is configurable.

Note: The existing `docker-compose.prod.yml` has an inconsistency — the app service uses `DATABASE_PASSWORD` (single underscore, doesn't match nested delimiter) while the worker uses `DATABASE__PASSWORD`. The new compose file standardizes on `DATABASE__PASSWORD` (double underscore) for all services.

## Documentation updates

- **README.md**: Add "Production Deployment" section covering:
  - Prerequisites (Docker Compose on VM, domain with DNS configured)
  - `task prod:setup` workflow
  - `task prod:deploy` workflow
  - Subdomain overview
- **CLAUDE.md**: Add `prod:setup` and `prod:deploy` to the key commands table.
