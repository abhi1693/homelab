#!/usr/bin/env bash

set -euo pipefail

REPOSITORY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPOSITORY_ROOT

# renovate: datasource=github-releases depName=yannh/kubeconform
KUBECONFORM_VERSION=v0.6.7
# renovate: datasource=github-releases depName=mvdan/sh
SHFMT_VERSION=v3.10.0
# renovate: datasource=github-releases depName=hadolint/hadolint
HADOLINT_VERSION=v2.12.0

require_command() {
  local command_name="$1"
  local version_hint="${2:-}"

  if command -v "${command_name}" > /dev/null 2>&1; then
    return 0
  fi

  if [[ -n "${version_hint}" ]]; then
    printf 'error: %s %s is required on PATH\n' "${command_name}" "${version_hint}" >&2
  else
    printf 'error: %s is required on PATH\n' "${command_name}" >&2
  fi
  return 1
}

validate_ansible() {
  require_command ansible-galaxy
  require_command ansible-playbook
  require_command ansible-lint

  ansible-galaxy collection install \
    -r infrastructure/ansible/collections/requirements.yml

  (
    cd infrastructure/ansible
    export ANSIBLE_VARS_ENABLED=host_group_vars
    ansible-playbook --syntax-check playbooks/site.yml
    ansible-lint --profile min
  )
}

validate_yaml() {
  require_command python3
  require_command yamllint

  yamllint "$@"
}

validate_kubernetes_resource_bounds() {
  require_command python3

  python3 scripts/check-kubernetes-resource-bounds.py "$@"
}

validate_renovate_policy() {
  require_command python3

  python3 scripts/check-renovate-policy.py
}

validate_kubernetes() {
  require_command kubeconform "${KUBECONFORM_VERSION}"

  kubeconform \
    -summary \
    -strict \
    -ignore-missing-schemas \
    "$@"
}

validate_terraform() {
  require_command terraform

  terraform fmt -check -recursive coder/templates

  local -a templates=()
  mapfile -d '' templates < <(
    find coder/templates -mindepth 2 -maxdepth 2 -name main.tf -printf '%h\0'
  )

  for template in "${templates[@]}"; do
    printf 'Validating %s\n' "${template}"
    terraform -chdir="${template}" init -backend=false -input=false
    terraform -chdir="${template}" validate
  done
}

validate_shell() {
  require_command shfmt "${SHFMT_VERSION}"
  require_command shellcheck

  if ! shfmt -d -i 2 -ci -sr "$@"; then
    printf 'warning: shfmt reported formatting differences\n' >&2
  fi
  shellcheck --shell=bash "$@"
}

validate_dockerfiles() {
  require_command hadolint "${HADOLINT_VERSION}"

  if ! hadolint "$@"; then
    printf 'warning: hadolint reported lint findings\n' >&2
  fi
}

cd "${REPOSITORY_ROOT}"

case "${1:-}" in
  ansible)
    validate_ansible
    ;;
  yaml)
    shift
    validate_yaml "$@"
    ;;
  kubernetes-resource-bounds)
    shift
    validate_kubernetes_resource_bounds "$@"
    ;;
  renovate-policy)
    validate_renovate_policy
    ;;
  kubernetes)
    shift
    validate_kubernetes "$@"
    ;;
  terraform)
    validate_terraform
    ;;
  shell)
    shift
    validate_shell "$@"
    ;;
  dockerfiles)
    shift
    validate_dockerfiles "$@"
    ;;
  *)
    printf '%s\n' \
      "usage: $0 {ansible|yaml|kubernetes-resource-bounds|renovate-policy|kubernetes|terraform|shell|dockerfiles} [files ...]" >&2
    exit 2
    ;;
esac
