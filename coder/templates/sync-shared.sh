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

for template in "${templates[@]}"; do
  mkdir -p "$root/$template/shared/scripts"
  rm -f "$root/$template/shared/scripts/"*.sh
  cp "$root/_shared/scripts/"*.sh "$root/$template/shared/scripts/"
done
