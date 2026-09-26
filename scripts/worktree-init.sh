#!/usr/bin/env bash
# Prepare this checkout (usually a git worktree) for local development.
#
#   - copies .env from the root checkout ($ORCA_ROOT_PATH) or from .env.example
#   - derives a per-branch database name and API/WEB port offset
#   - creates the databases with createdb (native Postgres on localhost, no Docker)
#   - points STORAGE_BACKEND=local at a folder inside this worktree
#   - installs api/ and web/ dependencies if that part has code
#   - runs alembic migrations if api/ has them
#
# Idempotent: re-running only rewrites the derived .env lines and skips work
# that is already done. Usage:  scripts/worktree-init.sh [--no-deps]
set -euo pipefail

WORKTREE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WORKTREE"

NO_DEPS=0
for arg in "$@"; do
  case "$arg" in
    --no-deps) NO_DEPS=1 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '[worktree-init] %s\n' "$*"; }
die() { printf '[worktree-init] error: %s\n' "$*" >&2; exit 1; }

# --- 1. locate the root checkout and seed .env --------------------------------
ROOT="${ORCA_ROOT_PATH:-}"
if [ -z "$ROOT" ]; then
  # first line of `git worktree list` is the main checkout
  ROOT="$(git worktree list --porcelain 2>/dev/null | awk '/^worktree /{print $2; exit}')"
fi
ROOT="${ROOT:-$WORKTREE}"

if [ ! -f .env ]; then
  if [ -f "$ROOT/.env" ] && [ "$ROOT" != "$WORKTREE" ]; then
    cp "$ROOT/.env" .env
    log "copied .env from $ROOT"
  else
    cp .env.example .env
    log "no root .env found; seeded .env from .env.example"
  fi
else
  log ".env already present; keeping it and refreshing derived values"
fi

# --- 2. derive per-branch names -----------------------------------------------
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo detached)"
# lower-case, non [a-z0-9] -> _, collapse runs, trim, cap length so the
# Postgres identifier (63 bytes) still fits with the _test suffix
SLUG="$(printf '%s' "$BRANCH" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/_/g; s/^_+//; s/_+$//' | cut -c1-32)"
SLUG="${SLUG:-detached}"

DB_PREFIX="foodverse_contracts"
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  DB_NAME="$DB_PREFIX"
  OFFSET=0
else
  DB_NAME="${DB_PREFIX}_${SLUG}"
  # stable 1..99 offset from the slug so ports never collide with main (0)
  OFFSET=$(( ( $(printf '%s' "$SLUG" | cksum | cut -d' ' -f1) % 99 ) + 1 ))
fi
TEST_DB_NAME="${DB_NAME}_test"
API_PORT=$(( 8000 + OFFSET ))
WEB_PORT=$(( 5173 + OFFSET ))
STORAGE_DIR="$WORKTREE/.local-storage"

# --- 3. read connection details from the existing DATABASE_URL ----------------
# format: postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DBNAME
env_get() { sed -nE "s/^$1=([^#]*).*/\1/p" .env | tail -n1 | sed -E 's/[[:space:]]+$//'; }
BASE_URL="$(env_get DATABASE_URL)"
[ -n "$BASE_URL" ] || die "DATABASE_URL missing from .env"
PG_USER="$(printf '%s' "$BASE_URL" | sed -E 's#^[a-z+]+://([^:/@]+)(:[^@]*)?@.*#\1#')"
PG_PASS="$(printf '%s' "$BASE_URL" | sed -nE 's#^[a-z+]+://[^:/@]+:([^@]*)@.*#\1#p')"
PG_HOST="$(printf '%s' "$BASE_URL" | sed -E 's#^[a-z+]+://[^@]*@([^:/]+).*#\1#')"
PG_PORT="$(printf '%s' "$BASE_URL" | sed -nE 's#^[a-z+]+://[^@]*@[^:/]+:([0-9]+)/.*#\1#p')"
PG_PORT="${PG_PORT:-5432}"
RET_URL="$(env_get RETENTION_DATABASE_URL)"
RET_USER="$(printf '%s' "$RET_URL" | sed -nE 's#^[a-z+]+://([^:/@]+)(:[^@]*)?@.*#\1#p')"
RET_PASS="$(printf '%s' "$RET_URL" | sed -nE 's#^[a-z+]+://[^:/@]+:([^@]*)@.*#\1#p')"

url_with_db() { printf '%s' "$1" | sed -E "s#(://[^/]+)/[^?]*#\1/$2#"; }

# --- 4. write derived values into .env (replace line or append) ---------------
env_set() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" .env; then
    # keep any trailing comment on the existing line
    local comment
    comment="$(sed -nE "s/^${key}=[^#]*(#.*)?$/\1/p" .env | tail -n1)"
    local tmp; tmp="$(mktemp)"
    awk -v k="$key" -v v="$value" -v c="$comment" '
      index($0, k"=")==1 { if (c!="") print k"="v"   "c; else print k"="v; next } { print }
    ' .env > "$tmp" && mv "$tmp" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}
env_set DATABASE_URL "$(url_with_db "$BASE_URL" "$DB_NAME")"
env_set TEST_DATABASE_URL "$(url_with_db "$(env_get TEST_DATABASE_URL)" "$TEST_DB_NAME")"
[ -n "$RET_URL" ] && env_set RETENTION_DATABASE_URL "$(url_with_db "$RET_URL" "$DB_NAME")"
env_set API_PORT "$API_PORT"
env_set WEB_PORT "$WEB_PORT"
env_set API_BASE_URL "http://localhost:${API_PORT}"
env_set WEB_BASE_URL "http://localhost:${WEB_PORT}"
env_set CORS_ALLOWED_ORIGINS "http://localhost:${WEB_PORT}"
env_set VITE_API_BASE_URL "http://localhost:${API_PORT}/api/v1"
env_set STORAGE_BACKEND local
env_set LOCAL_STORAGE_DIR "$STORAGE_DIR"
mkdir -p "$STORAGE_DIR"
log "branch=$BRANCH db=$DB_NAME test_db=$TEST_DB_NAME api_port=$API_PORT web_port=$WEB_PORT"
log "storage=$STORAGE_DIR"

# --- 5. databases (native Postgres; roles created once, databases per branch) --
command -v createdb >/dev/null || die "createdb not found; install Postgres (brew install postgresql@16) and add it to PATH"
pg_isready -h "$PG_HOST" -p "$PG_PORT" -q || die "Postgres is not accepting connections on $PG_HOST:$PG_PORT (brew services start postgresql@16)"

# psql as the current OS user (Homebrew's default superuser) for role checks;
# fall back to the app role if the OS user has no role.
admin_psql() { psql -X -q -h "$PG_HOST" -p "$PG_PORT" -d postgres -tA "$@"; }
if ! admin_psql -c 'select 1' >/dev/null 2>&1; then
  admin_psql() { PGPASSWORD="$PG_PASS" psql -X -q -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d postgres -tA "$@"; }
fi
admin_psql -c 'select 1' >/dev/null 2>&1 || die "cannot connect to Postgres on $PG_HOST:$PG_PORT as $(whoami) or $PG_USER"

ensure_role() {
  local role="$1" pass="$2" extra="$3"
  if [ "$(admin_psql -c "select 1 from pg_roles where rolname='$role'")" != "1" ]; then
    admin_psql -c "create role \"$role\" login password '$pass' $extra" >/dev/null
    log "created role $role"
  fi
}
ensure_role "$PG_USER" "$PG_PASS" "createdb"
[ -n "$RET_USER" ] && ensure_role "$RET_USER" "$RET_PASS" ""

ensure_db() {
  local db="$1"
  if [ "$(admin_psql -c "select 1 from pg_database where datname='$db'")" = "1" ]; then
    log "database $db exists"
  else
    PGPASSWORD="$PG_PASS" createdb -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -O "$PG_USER" "$db"
    log "created database $db"
  fi
}
ensure_db "$DB_NAME"
ensure_db "$TEST_DB_NAME"

# --- 6. dependencies and migrations, only where code exists -------------------
if [ "$NO_DEPS" -eq 0 ]; then
  if [ -f api/pyproject.toml ]; then
    command -v uv >/dev/null || die "uv not found (brew install uv)"
    log "installing api deps"
    (cd api && uv sync --quiet)
  else
    log "api/ has no pyproject.toml yet; skipping deps"
  fi
  if [ -f web/package.json ]; then
    command -v npm >/dev/null || die "npm not found"
    log "installing web deps"
    if [ -f web/package-lock.json ]; then (cd web && npm ci --no-audit --no-fund --silent); else (cd web && npm install --no-audit --no-fund --silent); fi
  else
    log "web/ has no package.json yet; skipping deps"
  fi
fi

if [ -f api/alembic.ini ]; then
  log "running migrations"
  (cd api && set -a && . ../.env && set +a && uv run alembic upgrade head)
else
  log "api/ has no alembic.ini yet; skipping migrations"
fi

log "done. next:  set -a; source .env; set +a"
