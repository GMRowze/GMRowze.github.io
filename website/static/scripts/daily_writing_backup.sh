#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

LABEL="${WRITING_BACKUP_LABEL:-backup}"
MESSAGE="${WRITING_BACKUP_MESSAGE:-automatic writing backup}"
REMOTE="${WRITING_BACKUP_REMOTE:-origin}"
BRANCH="${WRITING_BACKUP_BRANCH:-}"

cd "$REPO_ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not inside a git repository: $REPO_ROOT" >&2
  exit 1
fi

python3 website/static/scripts/generate_writing_stats.py

git add -A

if git diff --cached --quiet; then
  echo "No changes to commit."
  exit 0
fi

timestamp="$(date '+%Y-%m-%d %H:%M')"
git commit -m "${LABEL}: ${MESSAGE} (${timestamp})"

if [ -z "$BRANCH" ]; then
  BRANCH="$(git branch --show-current)"
fi

if [ -z "$BRANCH" ]; then
  echo "Could not determine current branch; commit was created but not pushed." >&2
  exit 1
fi

git push "$REMOTE" "$BRANCH"
