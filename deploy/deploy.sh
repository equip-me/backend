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

# ── Parse arguments ─────────────────────────────────────
APP_VERSION=""
FRONTEND_VERSION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --app)
            [[ $# -lt 2 ]] && error "--app requires a version argument"
            APP_VERSION="$2"; shift 2 ;;
        --frontend)
            [[ $# -lt 2 ]] && error "--frontend requires a version argument"
            FRONTEND_VERSION="$2"; shift 2 ;;
        *)
            error "Unknown argument: $1\nUsage: $0 --app <version> --frontend <version>" ;;
    esac
done

if [[ -z "$APP_VERSION" && -z "$FRONTEND_VERSION" ]]; then
    echo "Usage: $0 --app <version> [--frontend <version>]"
    echo "       $0 --frontend <version> [--app <version>]"
    echo ""
    echo "Examples:"
    echo "  $0 --app 0.5.0"
    echo "  $0 --frontend 1.0.0"
    echo "  $0 --app 0.5.0 --frontend 1.0.0"
    exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
    error "dist/.env not found. Run setup.sh first."
fi

# ── Read VM_HOST from .env ──────────────────────────────
VM_HOST=$(grep '^VM_HOST=' "$ENV_FILE" | cut -d'=' -f2-)
if [[ -z "$VM_HOST" ]]; then
    error "VM_HOST not found in dist/.env"
fi

# ── Update versions ─────────────────────────────────────
SERVICES=()

if [[ -n "$APP_VERSION" ]]; then
    info "Updating APP_VERSION to ${APP_VERSION}..."
    sed -i.bak "s/^APP_VERSION=.*/APP_VERSION=${APP_VERSION}/" "$ENV_FILE"
    rm -f "$ENV_FILE.bak"
    SERVICES+=(app worker)
fi

if [[ -n "$FRONTEND_VERSION" ]]; then
    info "Updating FRONTEND_VERSION to ${FRONTEND_VERSION}..."
    sed -i.bak "s/^FRONTEND_VERSION=.*/FRONTEND_VERSION=${FRONTEND_VERSION}/" "$ENV_FILE"
    rm -f "$ENV_FILE.bak"
    SERVICES+=(frontend)
fi

# ── Deploy ──────────────────────────────────────────────
info "Deploying to ${VM_HOST}..."

scp "$ENV_FILE" "$VM_HOST:~/rental-platform/.env"
ssh "$VM_HOST" "cd ~/rental-platform && docker compose pull ${SERVICES[*]} && docker compose up -d ${SERVICES[*]}"

ok "Deployed: ${SERVICES[*]}"
info "Run 'ssh ${VM_HOST} \"cd ~/rental-platform && docker compose ps\"' to check status."
