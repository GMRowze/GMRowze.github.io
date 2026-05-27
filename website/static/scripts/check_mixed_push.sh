#!/usr/bin/env bash
set -euo pipefail

ZERO_SHA="0000000000000000000000000000000000000000"

zones="${PUSH_ZONE_ROOTS:-drafts published website files .github}"
ignored_prefixes="${PUSH_ZONE_IGNORE_PREFIXES:-website/static/data/writing/ website/public/}"

zone_for_path() {
  local path="$1"
  local zone

  for zone in $zones; do
    case "$path" in
      "$zone"|"$zone"/*)
        printf '%s\n' "$zone"
        return 0
        ;;
    esac
  done

  printf '%s\n' "repo-root"
}

is_ignored_path() {
  local path="$1"
  local prefix

  for prefix in $ignored_prefixes; do
    case "$path" in
      "$prefix"*) return 0 ;;
    esac
  done

  return 1
}

range_for_ref() {
  local local_sha="$1"
  local remote_sha="$2"

  if [ "$remote_sha" = "$ZERO_SHA" ]; then
    printf '%s\n' "$local_sha"
  else
    printf '%s..%s\n' "$remote_sha" "$local_sha"
  fi
}

check_range() {
  local range="$1"
  local ref_name="$2"
  local changed_file
  local zone
  local zones_seen_file
  local files_seen_file

  zones_seen_file="$(mktemp)"
  files_seen_file="$(mktemp)"

  while IFS= read -r changed_file; do
    [ -n "$changed_file" ] || continue
    if is_ignored_path "$changed_file"; then
      continue
    fi
    zone="$(zone_for_path "$changed_file")"
    printf '%s\n' "$zone" >> "$zones_seen_file"
    printf '%s\t%s\n' "$zone" "$changed_file" >> "$files_seen_file"
  done < <(git diff --name-only "$range")

  if [ ! -s "$zones_seen_file" ]; then
    rm -f "$zones_seen_file" "$files_seen_file"
    return 0
  fi

  local zone_count
  zone_count="$(sort -u "$zones_seen_file" | wc -l | tr -d ' ')"
  if [ "$zone_count" -le 1 ]; then
    rm -f "$zones_seen_file" "$files_seen_file"
    return 0
  fi

  echo "Refusing mixed-zone push to $ref_name." >&2
  echo "This push changes files in more than one publishing zone:" >&2
  echo >&2

  while IFS= read -r zone; do
    echo "[$zone]" >&2
    awk -F '\t' -v zone="$zone" '$1 == zone { print "  " $2 }' "$files_seen_file" >&2
  done < <(sort -u "$zones_seen_file")

  echo >&2
  echo "Split this into separate pushes, or bypass intentionally with:" >&2
  echo "  git push --no-verify" >&2
  echo >&2
  echo "Config knobs:" >&2
  echo "  PUSH_ZONE_ROOTS='drafts published website files .github'" >&2
  echo "  PUSH_ZONE_IGNORE_PREFIXES='website/static/data/writing/ website/public/'" >&2
  rm -f "$zones_seen_file" "$files_seen_file"
  return 1
}

main() {
  local remote_name="${1:-origin}"
  local remote_url="${2:-}"
  local local_ref
  local local_sha
  local remote_ref
  local remote_sha
  local failed=0

  while read -r local_ref local_sha remote_ref remote_sha; do
    [ -n "${local_sha:-}" ] || continue
    if [ "$local_sha" = "$ZERO_SHA" ]; then
      continue
    fi
    if ! check_range "$(range_for_ref "$local_sha" "$remote_sha")" "$remote_ref"; then
      failed=1
    fi
  done

  if [ "$failed" -ne 0 ]; then
    echo "Mixed push blocked for $remote_name $remote_url." >&2
    exit 1
  fi
}

main "$@"
