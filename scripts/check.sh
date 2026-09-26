#!/usr/bin/env bash
# Run every check CI runs, for whichever parts of the repo have code:
#   api/  ruff check, ruff format --check, mypy (if app/ exists), pytest
#   web/  npm run lint, npm run typecheck (if defined), npm test
# Exit 0 when everything passes or there is nothing to check, non-zero otherwise.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

failures=()
ran=0

section() { printf '\n==> %s\n' "$*"; }
run() {
  # run <label> <cmd...>; records a failure instead of aborting so every check reports
  local label="$1"; shift
  ran=1
  section "$label"
  if "$@"; then printf -- '--> %s: ok\n' "$label"; else failures+=("$label"); printf -- '--> %s: FAILED\n' "$label"; fi
}

# load .env so pytest and the app see TEST_DATABASE_URL etc. CI passes env directly.
if [ -f .env ]; then set -a; . ./.env; set +a; fi

# --- api ----------------------------------------------------------------------
if [ -f api/pyproject.toml ]; then
  if ! command -v uv >/dev/null; then echo "uv not found (brew install uv)" >&2; exit 1; fi
  pushd api >/dev/null
  uv sync --quiet || { echo "uv sync failed" >&2; exit 1; }
  run "api: ruff check"  uv run ruff check .
  run "api: ruff format" uv run ruff format --check .
  if [ -d app ]; then run "api: mypy" uv run mypy app; fi
  run "api: pytest" uv run pytest -q
  popd >/dev/null
else
  echo "api/: no pyproject.toml, skipping"
fi

# --- web ----------------------------------------------------------------------
if [ -f web/package.json ]; then
  if ! command -v npm >/dev/null; then echo "npm not found" >&2; exit 1; fi
  pushd web >/dev/null
  if [ ! -d node_modules ]; then
    if [ -f package-lock.json ]; then npm ci --no-audit --no-fund --silent; else npm install --no-audit --no-fund --silent; fi \
      || { echo "npm install failed" >&2; exit 1; }
  fi
  has_script() { node -e "process.exit(require('./package.json').scripts?.['$1'] ? 0 : 1)"; }
  if has_script lint;      then run "web: lint"      npm run --silent lint;      else echo "web: no lint script, skipping"; fi
  if has_script typecheck; then run "web: typecheck" npm run --silent typecheck; else echo "web: no typecheck script, skipping"; fi
  if has_script test;      then run "web: test"      npm test --silent -- --run; else echo "web: no test script, skipping"; fi
  popd >/dev/null
else
  echo "web/: no package.json, skipping"
fi

# --- summary ------------------------------------------------------------------
printf '\n'
if [ "${#failures[@]}" -gt 0 ]; then
  printf 'check.sh: %d check(s) FAILED:\n' "${#failures[@]}"
  printf '  - %s\n' "${failures[@]}"
  exit 1
fi
if [ "$ran" -eq 0 ]; then echo "check.sh: nothing to check yet (no api/ or web/ code)"; else echo "check.sh: all checks passed"; fi
exit 0
