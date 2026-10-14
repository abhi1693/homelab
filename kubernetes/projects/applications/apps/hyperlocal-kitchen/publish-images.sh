#!/usr/bin/env bash
set -euo pipefail

source_repo="${1:?Usage: publish-images.sh /path/to/hyperlocal-kitchen}"
source_ref="168f2c82c842f2a368b35bd796c3f240c3b1170e"
source_sha="$(git -C "$source_repo" rev-parse "${source_ref}^{commit}")"
build_context="$(mktemp -d /tmp/hyperlocal-kitchen-images.XXXXXX)"
trap 'rm -rf -- "$build_context"' EXIT

git -C "$source_repo" archive "$source_sha" | tar -x -C "$build_context"
for component in backend admin; do
  dockerfile=Dockerfile
  if [[ "$component" == admin ]]; then
    dockerfile=apps/admin/Dockerfile
  fi
  image="ghcr.io/abhi1693/hyperlocal-kitchen/${component}:sha-${source_sha}"
  docker buildx build --platform linux/arm64 \
    --file "$build_context/$dockerfile" --tag "$image" --push "$build_context"
  docker buildx imagetools inspect "$image"
done
