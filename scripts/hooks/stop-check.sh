#!/usr/bin/env bash
# Claude Code Stop hook: refuse to let the agent finish while scripts/check.sh fails.
# Reads the hook payload on stdin; when stop_hook_active is true we are already
# inside a hook-triggered continuation, so exit 0 to avoid an infinite loop.
set -uo pipefail

payload="$(cat)"
if command -v jq >/dev/null 2>&1; then
  active="$(printf '%s' "$payload" | jq -r '.stop_hook_active // false' 2>/dev/null || echo false)"
else
  case "$payload" in *'"stop_hook_active"'*true*) active=true ;; *) active=false ;; esac
fi
[ "$active" = "true" ] && exit 0

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# nothing to check yet: do not block
[ -f "$ROOT/api/pyproject.toml" ] || [ -f "$ROOT/web/package.json" ] || exit 0

out="$("$ROOT/scripts/check.sh" 2>&1)"
status=$?
if [ "$status" -ne 0 ]; then
  {
    echo "scripts/check.sh failed (exit $status). Fix the failures before finishing; do not weaken tests or limits."
    echo "--- last 80 lines of output ---"
    printf '%s\n' "$out" | tail -n 80
  } >&2
  exit 2
fi
exit 0
