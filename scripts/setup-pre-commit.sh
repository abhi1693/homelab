#!/usr/bin/env bash

set -euo pipefail

REPOSITORY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPOSITORY_ROOT

readonly REQUIREMENTS_FILE="${REPOSITORY_ROOT}/.github/requirements/pre-commit.txt"
readonly TOOL_BIN_DIR="${UV_TOOL_BIN_DIR:-${HOME}/.local/bin}"
readonly VALIDATION_SCRIPT="${REPOSITORY_ROOT}/scripts/run-pre-commit-validation.sh"

read_tool_version() {
  local variable_name="$1"

  sed -n "s/^${variable_name}=//p" "${VALIDATION_SCRIPT}"
}

KUBECONFORM_VERSION="$(read_tool_version KUBECONFORM_VERSION)"
SHFMT_VERSION="$(read_tool_version SHFMT_VERSION)"
HADOLINT_VERSION="$(read_tool_version HADOLINT_VERSION)"
readonly KUBECONFORM_VERSION SHFMT_VERSION HADOLINT_VERSION

for required_version in KUBECONFORM_VERSION SHFMT_VERSION HADOLINT_VERSION; do
  if [[ ! "${!required_version}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf 'error: expected one pinned %s in %s\n' "${required_version}" "${VALIDATION_SCRIPT}" >&2
    exit 1
  fi
done

require_command() {
  local command_name="$1"
  local install_hint="${2:-}"

  if command -v "${command_name}" > /dev/null 2>&1; then
    return 0
  fi

  printf 'error: %s is required' "${command_name}" >&2
  if [[ -n "${install_hint}" ]]; then
    printf ' (%s)' "${install_hint}" >&2
  fi
  printf '\n' >&2
  return 1
}

download() {
  local url="$1"
  local destination="$2"

  curl \
    --fail \
    --location \
    --proto '=https' \
    --show-error \
    --silent \
    --tlsv1.2 \
    --output "${destination}" \
    "${url}"
}

verify_checksum() {
  local asset_path="$1"
  local checksum_path="$2"
  local asset_name="$3"
  local expected_checksum
  local actual_checksum

  expected_checksum="$(awk -v asset="${asset_name}" '$2 == asset || $2 == "*" asset { print $1; exit }' "${checksum_path}")"
  if [[ ! "${expected_checksum}" =~ ^[a-fA-F0-9]{64}$ ]]; then
    printf 'error: no valid SHA-256 checksum found for %s\n' "${asset_name}" >&2
    return 1
  fi

  actual_checksum="$(sha256sum "${asset_path}")"
  actual_checksum="${actual_checksum%% *}"
  if [[ "${actual_checksum}" != "${expected_checksum}" ]]; then
    printf 'error: SHA-256 mismatch for %s\n' "${asset_name}" >&2
    return 1
  fi
}

require_command uv 'https://docs.astral.sh/uv/getting-started/installation/'
require_command curl
require_command tar
require_command sha256sum
require_command install
require_command terraform 'https://developer.hashicorp.com/terraform/install'
require_command shellcheck 'install the shellcheck OS package'

if [[ "$(uname -s)" != "Linux" ]]; then
  printf 'error: automatic validator installation currently supports Linux only\n' >&2
  exit 1
fi

case "$(uname -m)" in
  x86_64)
    release_arch=amd64
    hadolint_arch=x86_64
    ;;
  aarch64 | arm64)
    release_arch=arm64
    hadolint_arch=arm64
    ;;
  *)
    printf 'error: unsupported Linux architecture: %s\n' "$(uname -m)" >&2
    exit 1
    ;;
esac
readonly release_arch hadolint_arch

pre_commit_version="$(sed -n 's/^pre-commit==//p' "${REQUIREMENTS_FILE}")"
if [[ ! "${pre_commit_version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  printf 'error: expected one pinned pre-commit version in %s\n' "${REQUIREMENTS_FILE}" >&2
  exit 1
fi
readonly pre_commit_version

install -d -m 0755 "${TOOL_BIN_DIR}"
export PATH="${TOOL_BIN_DIR}:${PATH}"
export UV_TOOL_BIN_DIR="${TOOL_BIN_DIR}"

uv tool install \
  --force \
  --with-requirements "${REQUIREMENTS_FILE}" \
  --with-executables-from ansible-core \
  --with-executables-from ansible-lint \
  --with-executables-from yamllint \
  "pre-commit==${pre_commit_version}"

temporary_directory="$(mktemp -d)"
readonly temporary_directory
cleanup() {
  rm -rf -- "${temporary_directory}"
}
trap cleanup EXIT

kubeconform_asset="kubeconform-linux-${release_arch}.tar.gz"
download \
  "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/${kubeconform_asset}" \
  "${temporary_directory}/${kubeconform_asset}"
download \
  "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/CHECKSUMS" \
  "${temporary_directory}/kubeconform-CHECKSUMS"
verify_checksum \
  "${temporary_directory}/${kubeconform_asset}" \
  "${temporary_directory}/kubeconform-CHECKSUMS" \
  "${kubeconform_asset}"
mkdir "${temporary_directory}/kubeconform"
tar -xzf "${temporary_directory}/${kubeconform_asset}" -C "${temporary_directory}/kubeconform"
install -m 0755 "${temporary_directory}/kubeconform/kubeconform" "${TOOL_BIN_DIR}/kubeconform"

shfmt_asset="shfmt_${SHFMT_VERSION}_linux_${release_arch}"
download \
  "https://github.com/mvdan/sh/releases/download/${SHFMT_VERSION}/${shfmt_asset}" \
  "${temporary_directory}/${shfmt_asset}"
download \
  "https://github.com/mvdan/sh/releases/download/${SHFMT_VERSION}/sha256sums.txt" \
  "${temporary_directory}/shfmt-sha256sums.txt"
verify_checksum \
  "${temporary_directory}/${shfmt_asset}" \
  "${temporary_directory}/shfmt-sha256sums.txt" \
  "${shfmt_asset}"
install -m 0755 "${temporary_directory}/${shfmt_asset}" "${TOOL_BIN_DIR}/shfmt"

hadolint_asset="hadolint-Linux-${hadolint_arch}"
download \
  "https://github.com/hadolint/hadolint/releases/download/${HADOLINT_VERSION}/${hadolint_asset}" \
  "${temporary_directory}/${hadolint_asset}"
download \
  "https://github.com/hadolint/hadolint/releases/download/${HADOLINT_VERSION}/${hadolint_asset}.sha256" \
  "${temporary_directory}/${hadolint_asset}.sha256"
verify_checksum \
  "${temporary_directory}/${hadolint_asset}" \
  "${temporary_directory}/${hadolint_asset}.sha256" \
  "${hadolint_asset}"
install -m 0755 "${temporary_directory}/${hadolint_asset}" "${TOOL_BIN_DIR}/hadolint"

cd "${REPOSITORY_ROOT}"
pre-commit validate-config
pre-commit install --install-hooks

printf 'Installed repository validation tools in %s\n' "${TOOL_BIN_DIR}"
pre-commit --version
ansible-lint --version
yamllint --version
kubeconform -v
shfmt --version
shellcheck --version | sed -n '1,2p'
hadolint --version
terraform version | sed -n '1p'
