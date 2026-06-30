#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
templates=(
  "netbox"
  "python-3-12"
  "nodejs-22"
  "nodejs-24"
  "nodejs-26"
  "ubuntu-desktop"
)

status=0
for template in "${templates[@]}"; do
  for target in "$root/$template/shared/scripts/"*.sh; do
    name="$(basename "$target")"
    source="$root/_shared/scripts/$name"
    if [ ! -f "$source" ]; then
      echo "stale shared file: $target" >&2
      status=1
    fi
  done

  for source in "$root/_shared/scripts/"*.sh; do
    name="$(basename "$source")"
    target="$root/$template/shared/scripts/$name"
    if [ ! -f "$target" ]; then
      echo "missing shared file: $target" >&2
      status=1
      continue
    fi
    if ! cmp -s "$source" "$target"; then
      echo "shared file drifted: $target" >&2
      status=1
    fi
  done
done

exit "$status"
