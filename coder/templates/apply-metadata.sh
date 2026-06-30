#!/usr/bin/env bash
set -euo pipefail

templates=(
  "nodejs-22|Node.js 22 LTS|ARM64 Node.js 22 LTS workspace with Codex CLI, PyCharm Gateway, Longhorn home storage, and optional Docker sidecar."
  "nodejs-24|Node.js 24 LTS|ARM64 Node.js 24 LTS workspace with Codex CLI, PyCharm Gateway, Longhorn home storage, and optional Docker sidecar."
  "nodejs-26|Node.js 26 Current|ARM64 Node.js 26 Current workspace with Codex CLI, PyCharm Gateway, Longhorn home storage, and optional Docker sidecar."
  "netbox|NetBox 4.6 Plugin Dev|NetBox 4.6 plugin dev workspace with editable plugin checkout, PyCharm, PostgreSQL, Redis, and dev server."
  "python-3-12|Python 3.12 + Services|ARM64 Python 3.12 workspace with Codex CLI, uv, PyCharm Gateway, Longhorn storage, optional Docker, PostgreSQL, and Redis."
  "ubuntu-desktop|Ubuntu Desktop|ARM64 Ubuntu desktop with XFCE via Portable Desktop, Codex CLI, Node.js 24, Longhorn home storage, and optional Docker."
)

for template in "${templates[@]}"; do
  IFS="|" read -r slug display_name description <<<"$template"
  coder templates edit "$slug" \
    --display-name "$display_name" \
    --description "$description" \
    -y
done
