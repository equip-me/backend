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

# ── Validate arguments ───────────────────────────────────
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

# ── Update version ───────────────────────────────────────
info "Updating APP_VERSION to ${VERSION}..."
sed -i.bak "s/^APP_VERSION=.*/APP_VERSION=${VERSION}/" "$ENV_FILE"
rm -f "$ENV_FILE.bak"

# ── Deploy ───────────────────────────────────────────────
info "Deploying v${VERSION} to ${VM_HOST}..."

scp "$ENV_FILE" "$VM_HOST:~/rental-platform/.env"
ssh "$VM_HOST" "cd ~/rental-platform && docker compose pull app worker && docker compose up -d app worker"

ok "Deployed v${VERSION}"
info "Run 'ssh ${VM_HOST} \"cd ~/rental-platform && docker compose ps\"' to check status."
