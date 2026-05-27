#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
HOOK="$REPO_ROOT/.git/hooks/pre-push"

marker_start="# BEGIN rowze mixed push guard"
marker_end="# END rowze mixed push guard"

if [ ! -d "$REPO_ROOT/.git" ]; then
  echo "No .git directory found at $REPO_ROOT" >&2
  exit 1
fi

hook_block="$(cat <<'HOOK'
# BEGIN rowze mixed push guard
"$(git rev-parse --show-toplevel)/website/static/scripts/check_mixed_push.sh" "$@"
status=$?
if [ "$status" -ne 0 ]; then
  exit "$status"
fi
# END rowze mixed push guard
HOOK
)"

existing=""
if [ -f "$HOOK" ]; then
  existing="$(cat "$HOOK")"
fi

if printf '%s\n' "$existing" | grep -q "$marker_start"; then
  cleaned="$(printf '%s\n' "$existing" | sed "/$marker_start/,/$marker_end/d")"
else
  cleaned="$existing"
fi

if printf '%s\n' "$cleaned" | head -n 1 | grep -q '^#!'; then
  shebang="$(printf '%s\n' "$cleaned" | head -n 1)"
  body="$(printf '%s\n' "$cleaned" | tail -n +2)"
else
  shebang="#!/usr/bin/env bash"
  body="$cleaned"
fi

{
  printf '%s\n\n' "$shebang"
  printf '%s\n\n' "$hook_block"
  printf '%s\n' "$body" | sed '/^[[:space:]]*$/d'
} > "$HOOK"

chmod +x "$HOOK" "$REPO_ROOT/website/static/scripts/check_mixed_push.sh"

echo "Installed mixed push guard at .git/hooks/pre-push"
