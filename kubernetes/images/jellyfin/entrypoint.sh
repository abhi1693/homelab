#!/usr/bin/env bash
set -euo pipefail

ha_state_dir="${JELLYFIN_HA_STATE_DIR:-/tmp/jellyfin-ha}"
ha_alive_file="${ha_state_dir}/wrapper-alive"
ha_active_file="${ha_state_dir}/active"
ha_pid_file="${ha_state_dir}/jellyfin.pid"
healthcheck_url="${JELLYFIN_HEALTHCHECK_URL:-http://127.0.0.1:8096/}"

log() {
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
}

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

run_healthcheck() {
  local check="${1:-}"

  case "${check}" in
    startup)
      test -f "${ha_alive_file}"
      ;;
    liveness)
      test -f "${ha_alive_file}" || exit 1
      if [ -f "${ha_active_file}" ]; then
        curl -fsS --max-time 3 "${healthcheck_url}" >/dev/null
      fi
      ;;
    readiness)
      if [ -f "${ha_active_file}" ]; then
        curl -fsS --max-time 3 "${healthcheck_url}" >/dev/null
      elif is_true "${JELLYFIN_PASSIVE_READY:-false}"; then
        test -f "${ha_alive_file}"
      else
        exit 1
      fi
      ;;
    *)
      echo "Usage: $0 healthcheck startup|liveness|readiness" >&2
      exit 64
      ;;
  esac
}

if [ "${1:-}" = "healthcheck" ]; then
  shift
  run_healthcheck "$@"
  exit $?
fi

if [ "${JELLYFIN_CONFIG_DIR:-}" = "/config/config" ] || [ -z "${JELLYFIN_CONFIG_DIR:-}" ]; then
  export JELLYFIN_CONFIG_DIR=/config
fi

if [ "${JELLYFIN_DATA_DIR:-}" = "/config" ] || [ -z "${JELLYFIN_DATA_DIR:-}" ]; then
  export JELLYFIN_DATA_DIR=/data
fi

if [ "${JELLYFIN_LOG_DIR:-}" = "/config/log" ] || [ -z "${JELLYFIN_LOG_DIR:-}" ]; then
  export JELLYFIN_LOG_DIR=/logs
fi

config_root="${JELLYFIN_CONFIG_DIR}"
data_root="${JELLYFIN_DATA_DIR}"
image_plugins_dir=/opt/jellyfin/plugins
runtime_plugins_dir="${JELLYFIN_PLUGIN_DIR:-${data_root}/plugins}"
config_source_dirs="${JELLYFIN_CONFIG_SOURCE_DIRS:-}"
data_source_dirs="${JELLYFIN_DATA_SOURCE_DIRS:-}"
plugin_config_source_dirs="${JELLYFIN_PLUGIN_CONFIG_SOURCE_DIRS:-/opt/jellyfin/plugin-config:/opt/jellyfin/plugin-secrets}"
database_config="${JELLYFIN_DATABASE_CONFIG:-${config_root}/database.xml}"
shared_data_dir="${JELLYFIN_SHARED_DATA_DIR:-}"
shared_data_paths="${JELLYFIN_SHARED_DATA_PATHS:-metadata:data/collections:data/subtitles:data/livetv:data/playlists:data/imdb-ratings-cache:root:Shokofin}"
server_id="${JELLYFIN_SERVER_ID:-}"
device_id_file="${JELLYFIN_DEVICE_ID_FILE:-${data_root}/data/device.txt}"

now_rfc3339() {
  date -u '+%Y-%m-%dT%H:%M:%S.%6NZ'
}

k8s_request() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local content_type="${4:-application/json}"
  local token
  local curl_args

  token="$(<"${kube_token_file}")"
  curl_args=(
    -sS
    --connect-timeout "${kube_connect_timeout}"
    --max-time "${kube_request_timeout}"
    --cacert "${kube_ca_file}"
    -H "Authorization: Bearer ${token}"
    -H "Accept: application/json"
    -X "${method}"
    -o "${k8s_response_file}"
    -w "%{http_code}"
  )

  if [ -n "${body}" ]; then
    curl_args+=(
      -H "Content-Type: ${content_type}"
      --data "${body}"
    )
  fi

  if ! k8s_status="$(curl "${curl_args[@]}" "${kube_api}${path}")"; then
    k8s_status=000
  fi
  k8s_body="$(cat "${k8s_response_file}" 2>/dev/null || true)"
}

lease_is_available() {
  local lease_json="$1"
  local holder
  local renew_time
  local duration
  local renew_epoch
  local now_epoch

  holder="$(jq -r '.spec.holderIdentity // ""' <<< "${lease_json}")"
  if [ -z "${holder}" ] || [ "${holder}" = "${lease_identity}" ]; then
    return 0
  fi

  renew_time="$(jq -r '.spec.renewTime // .spec.acquireTime // ""' <<< "${lease_json}")"
  if [ -z "${renew_time}" ]; then
    return 0
  fi

  duration="$(jq -r --argjson fallback "${lease_duration_seconds}" '.spec.leaseDurationSeconds // $fallback' <<< "${lease_json}")"
  renew_epoch="$(date -u -d "${renew_time}" '+%s' 2>/dev/null || echo 0)"
  now_epoch="$(date -u '+%s')"

  [ $((now_epoch - renew_epoch)) -gt "${duration}" ]
}

lease_payload() {
  local name="$1"
  local namespace="$2"
  local holder="$3"
  local resource_version="$4"
  local acquire_time="$5"
  local renew_time="$6"
  local transitions="$7"

  jq -n \
    --arg name "${name}" \
    --arg namespace "${namespace}" \
    --arg holder "${holder}" \
    --arg resourceVersion "${resource_version}" \
    --arg acquireTime "${acquire_time}" \
    --arg renewTime "${renew_time}" \
    --argjson duration "${lease_duration_seconds}" \
    --argjson transitions "${transitions}" \
    '
    {
      apiVersion: "coordination.k8s.io/v1",
      kind: "Lease",
      metadata: {
        name: $name,
        namespace: $namespace
      },
      spec: {
        holderIdentity: $holder,
        leaseDurationSeconds: $duration,
        acquireTime: $acquireTime,
        renewTime: $renewTime,
        leaseTransitions: $transitions
      }
    }
    | if $resourceVersion != "" then .metadata.resourceVersion = $resourceVersion else . end
    '
}

try_acquire_or_renew_lease() {
  local path="/apis/coordination.k8s.io/v1/namespaces/${lease_namespace}/leases"
  local now
  local holder
  local resource_version
  local acquire_time
  local transitions
  local payload

  now="$(now_rfc3339)"
  k8s_request GET "${path}/${lease_name}"

  case "${k8s_status}" in
    200)
      if ! lease_is_available "${k8s_body}"; then
        holder="$(jq -r '.spec.holderIdentity // "unknown"' <<< "${k8s_body}")"
        log "Jellyfin passive: lease ${lease_namespace}/${lease_name} is held by ${holder}"
        return 1
      fi

      holder="$(jq -r '.spec.holderIdentity // ""' <<< "${k8s_body}")"
      resource_version="$(jq -r '.metadata.resourceVersion // ""' <<< "${k8s_body}")"
      transitions="$(jq -r '.spec.leaseTransitions // 0' <<< "${k8s_body}")"
      if [ "${holder}" = "${lease_identity}" ]; then
        acquire_time="$(jq -r '.spec.acquireTime // empty' <<< "${k8s_body}")"
      else
        acquire_time="${now}"
        transitions=$((transitions + 1))
      fi

      payload="$(lease_payload "${lease_name}" "${lease_namespace}" "${lease_identity}" "${resource_version}" "${acquire_time:-${now}}" "${now}" "${transitions}")"
      k8s_request PUT "${path}/${lease_name}" "${payload}"
      if [ "${k8s_status}" = "200" ]; then
        return 0
      fi
      log "Jellyfin passive: unable to update lease ${lease_namespace}/${lease_name}, Kubernetes API returned ${k8s_status}"
      return 1
      ;;
    404)
      payload="$(lease_payload "${lease_name}" "${lease_namespace}" "${lease_identity}" "" "${now}" "${now}" 0)"
      k8s_request POST "${path}" "${payload}"
      if [ "${k8s_status}" = "200" ] || [ "${k8s_status}" = "201" ]; then
        return 0
      fi
      log "Jellyfin passive: unable to create lease ${lease_namespace}/${lease_name}, Kubernetes API returned ${k8s_status}"
      return 1
      ;;
    *)
      log "Jellyfin passive: unable to read lease ${lease_namespace}/${lease_name}, Kubernetes API returned ${k8s_status}"
      return 1
      ;;
  esac
}

release_lease() {
  local path="/apis/coordination.k8s.io/v1/namespaces/${lease_namespace}/leases"
  local holder
  local resource_version
  local acquire_time
  local transitions
  local payload

  k8s_request GET "${path}/${lease_name}" || true
  if [ "${k8s_status}" != "200" ]; then
    return 0
  fi

  holder="$(jq -r '.spec.holderIdentity // ""' <<< "${k8s_body}")"
  if [ "${holder}" != "${lease_identity}" ]; then
    return 0
  fi

  resource_version="$(jq -r '.metadata.resourceVersion // ""' <<< "${k8s_body}")"
  acquire_time="$(jq -r '.spec.acquireTime // empty' <<< "${k8s_body}")"
  transitions="$(jq -r '.spec.leaseTransitions // 0' <<< "${k8s_body}")"
  payload="$(lease_payload "${lease_name}" "${lease_namespace}" "" "${resource_version}" "${acquire_time:-$(now_rfc3339)}" "$(now_rfc3339)" "${transitions}")"
  k8s_request PUT "${path}/${lease_name}" "${payload}" || true
}

patch_own_pod_active_label() {
  local active="${1:-false}"
  local path
  local payload

  if ! is_true "${pod_active_label_enabled:-false}"; then
    return 0
  fi

  if [ -z "${lease_namespace:-}" ] || [ -z "${pod_name:-}" ] || [ -z "${pod_active_label_key:-}" ]; then
    log "Jellyfin active-passive: unable to patch active label, pod identity is incomplete"
    return 1
  fi

  path="/api/v1/namespaces/${lease_namespace}/pods/${pod_name}"
  if is_true "${active}"; then
    payload="$(jq -n \
      --arg key "${pod_active_label_key}" \
      --arg value "${pod_active_label_value}" \
      '{metadata:{labels:{($key):$value}}}')"
  else
    payload="$(jq -n \
      --arg key "${pod_active_label_key}" \
      '{metadata:{labels:{($key):null}}}')"
  fi

  k8s_request PATCH "${path}" "${payload}" "application/merge-patch+json"
  if [ "${k8s_status}" = "200" ]; then
    return 0
  fi

  log "Jellyfin active-passive: unable to patch pod label ${pod_active_label_key} on ${lease_namespace}/${pod_name}, Kubernetes API returned ${k8s_status}"
  return 1
}

wait_for_jellyfin_health() {
  while kill -0 "${jellyfin_pid}" 2>/dev/null; do
    if curl -fsS --max-time 3 "${healthcheck_url}" >/dev/null; then
      return 0
    fi
    sleep 2
  done

  return 1
}

run_jellyfin_with_lease() {
  local jellyfin_pid
  local failed_renews=0
  local exit_code=0

  mkdir -p "${ha_state_dir}"
  touch "${ha_alive_file}"
  rm -f "${ha_active_file}" "${ha_pid_file}"
  patch_own_pod_active_label false || true

  while ! try_acquire_or_renew_lease; do
    sleep "${lease_retry_seconds}"
  done

  log "Jellyfin active: acquired lease ${lease_namespace}/${lease_name} as ${lease_identity}"
  /jellyfin/jellyfin "$@" &
  jellyfin_pid="$!"
  printf '%s\n' "${jellyfin_pid}" > "${ha_pid_file}"
  touch "${ha_active_file}"

  if ! wait_for_jellyfin_health; then
    wait "${jellyfin_pid}" || exit_code="$?"
    rm -f "${ha_active_file}" "${ha_pid_file}"
    release_lease || true
    exit "${exit_code:-1}"
  fi

  if ! patch_own_pod_active_label true; then
    log "Jellyfin active: unable to advertise active backend, stopping Jellyfin"
    kill -TERM "${jellyfin_pid}" 2>/dev/null || true
    wait "${jellyfin_pid}" || true
    rm -f "${ha_active_file}" "${ha_pid_file}"
    release_lease || true
    exit 1
  fi

  terminate_jellyfin() {
    patch_own_pod_active_label false || true
    rm -f "${ha_active_file}" "${ha_pid_file}"
    if kill -0 "${jellyfin_pid}" 2>/dev/null; then
      kill -TERM "${jellyfin_pid}" 2>/dev/null || true
      wait "${jellyfin_pid}" || true
    fi
    release_lease || true
  }

  trap 'terminate_jellyfin; exit 143' TERM INT

  while kill -0 "${jellyfin_pid}" 2>/dev/null; do
    sleep "${lease_renew_seconds}"
    if try_acquire_or_renew_lease; then
      failed_renews=0
      continue
    fi

    failed_renews=$((failed_renews + 1))
    log "Jellyfin active: failed to renew lease ${failed_renews}/${lease_renew_failure_limit}"
    if [ "${failed_renews}" -ge "${lease_renew_failure_limit}" ]; then
      log "Jellyfin active: lease renewal failed, stopping Jellyfin"
      terminate_jellyfin
      exit 1
    fi
  done

  wait "${jellyfin_pid}" || exit_code="$?"
  patch_own_pod_active_label false || true
  rm -f "${ha_active_file}" "${ha_pid_file}"
  release_lease || true
  exit "${exit_code}"
}

write_postgres_database_config() {
  cat > "${database_config}" <<'XML'
<?xml version="1.0" encoding="utf-8"?>
<DatabaseConfigurationOptions xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <DatabaseType>PLUGIN_PROVIDER</DatabaseType>
  <CustomProviderOptions>
    <PluginAssembly>Jellyfin.Plugin.Pgsql.dll</PluginAssembly>
    <PluginName>PostgreSQL</PluginName>
    <ConnectionString></ConnectionString>
  </CustomProviderOptions>
  <LockingBehavior>NoLock</LockingBehavior>
</DatabaseConfigurationOptions>
XML
}

required_vars=(
  POSTGRES_HOST
  POSTGRES_PORT
  POSTGRES_DB
  POSTGRES_USER
  POSTGRES_PASSWORD
)

for var_name in "${required_vars[@]}"; do
  if [ -z "${!var_name:-}" ]; then
    echo "Missing required environment variable: ${var_name}" >&2
    exit 3
  fi
done

copy_source_dirs() {
  local target_dir="$1"
  local source_dirs="$2"

  IFS=':' read -r -a sources <<< "${source_dirs}"
  for source_dir in "${sources[@]}"; do
    if [ -d "${source_dir}" ]; then
      mkdir -p "${target_dir}"
      cp -R "${source_dir}/." "${target_dir}/"
    fi
  done
}

patch_jellyfin_enhanced_auto_skip_outro() {
  local requested_value="${JELLYFIN_ENHANCED_AUTO_SKIP_OUTRO:-}"
  local normalized_value
  local plugin_config_dir="${runtime_plugins_dir}/configurations"
  local config_file
  local settings_file
  local tmp_file

  if [ -z "${requested_value}" ]; then
    return
  fi

  case "$(printf '%s' "${requested_value}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on)
      normalized_value=true
      ;;
    0|false|no|off)
      normalized_value=false
      ;;
    *)
      echo "Invalid JELLYFIN_ENHANCED_AUTO_SKIP_OUTRO: expected a boolean value" >&2
      exit 6
      ;;
  esac

  if [ ! -d "${plugin_config_dir}" ]; then
    return
  fi

  while IFS= read -r -d '' config_file; do
    if [ "$(xmlstarlet select -t -v 'count(//*[local-name()="AutoSkipOutro"])' "${config_file}" 2>/dev/null || echo 0)" != "0" ]; then
      xmlstarlet edit \
        --inplace \
        -u '//*[local-name()="AutoSkipOutro"]' \
        -v "${normalized_value}" \
        "${config_file}"
      log "Jellyfin Enhanced: set AutoSkipOutro=${normalized_value} in ${config_file}"
    fi
  done < <(
    find "${plugin_config_dir}" -maxdepth 1 -type f \
      \( -name 'Jellyfin.Plugin.JellyfinEnhanced.xml' -o -name '*JellyfinEnhanced*.xml' -o -name '*Enhanced*.xml' \) \
      -print0
  )

  if [ ! -d "${plugin_config_dir}/Jellyfin.Plugin.JellyfinEnhanced" ]; then
    return
  fi

  while IFS= read -r -d '' settings_file; do
    if jq -e 'type == "object" and (has("AutoSkipOutro") or has("autoSkipOutro"))' "${settings_file}" >/dev/null 2>&1; then
      tmp_file="$(mktemp)"
      jq --argjson value "${normalized_value}" '
        if has("AutoSkipOutro") then .AutoSkipOutro = $value else . end
        | if has("autoSkipOutro") then .autoSkipOutro = $value else . end
      ' "${settings_file}" > "${tmp_file}"
      mv "${tmp_file}" "${settings_file}"
      log "Jellyfin Enhanced: set AutoSkipOutro=${normalized_value} in ${settings_file}"
    fi
  done < <(find "${plugin_config_dir}/Jellyfin.Plugin.JellyfinEnhanced" -mindepth 2 -maxdepth 2 -type f -name settings.json -print0)
}

link_shared_data_paths() {
  if [ -z "${shared_data_dir}" ]; then
    return
  fi

  mkdir -p "${shared_data_dir}"

  IFS=':' read -r -a shared_paths <<< "${shared_data_paths}"
  for relative_path in "${shared_paths[@]}"; do
    case "${relative_path}" in
      ''|/*|*'..'*)
        echo "Invalid shared data path: ${relative_path}" >&2
        exit 4
        ;;
    esac

    local target_path="${data_root}/${relative_path}"
    local shared_path="${shared_data_dir}/${relative_path}"

    mkdir -p "$(dirname "${target_path}")" "$(dirname "${shared_path}")"
    if [ ! -e "${shared_path}" ]; then
      mkdir -p "${shared_path}"
    fi

    rm -rf "${target_path}"
    ln -s "${shared_path}" "${target_path}"
  done
}

disable_trickplay_and_chapter_image_options() {
  if ! is_true "${JELLYFIN_DISABLE_TRICKPLAY_AND_CHAPTER_IMAGES:-false}"; then
    return
  fi

  if [ ! -d "${data_root}/root" ]; then
    return
  fi

  while IFS= read -r -d '' option_file; do
    if [ "$(xmlstarlet select -t -v 'count(//*[local-name()="EnableTrickplayImageExtraction"])' "${option_file}" 2>/dev/null || echo 0)" != "0" ]; then
      xmlstarlet edit \
        --inplace \
        -u '//*[local-name()="EnableTrickplayImageExtraction"]' \
        -v false \
        "${option_file}"
    fi

    if [ "$(xmlstarlet select -t -v 'count(//*[local-name()="ExtractTrickplayImagesDuringLibraryScan"])' "${option_file}" 2>/dev/null || echo 0)" != "0" ]; then
      xmlstarlet edit \
        --inplace \
        -u '//*[local-name()="ExtractTrickplayImagesDuringLibraryScan"]' \
        -v false \
        "${option_file}"
    fi

    if [ "$(xmlstarlet select -t -v 'count(//*[local-name()="EnableChapterImageExtraction"])' "${option_file}" 2>/dev/null || echo 0)" != "0" ]; then
      xmlstarlet edit \
        --inplace \
        -u '//*[local-name()="EnableChapterImageExtraction"]' \
        -v false \
        "${option_file}"
    fi

    if [ "$(xmlstarlet select -t -v 'count(//*[local-name()="ExtractChapterImagesDuringLibraryScan"])' "${option_file}" 2>/dev/null || echo 0)" != "0" ]; then
      xmlstarlet edit \
        --inplace \
        -u '//*[local-name()="ExtractChapterImagesDuringLibraryScan"]' \
        -v false \
        "${option_file}"
    fi

    log "Jellyfin library options: disabled trickplay and chapter image extraction in ${option_file}"
  done < <(find "${data_root}/root" -type f -name options.xml -print0)
}

write_server_id_file() {
  local normalized_server_id

  if [ -z "${server_id}" ]; then
    return
  fi

  normalized_server_id="$(printf '%s' "${server_id}" | tr '[:upper:]' '[:lower:]')"
  if [ "${#normalized_server_id}" -ne 32 ] || [[ "${normalized_server_id}" == *[!0-9a-f]* ]]; then
    echo "Invalid JELLYFIN_SERVER_ID: expected a 32-character hex string" >&2
    exit 5
  fi

  mkdir -p "$(dirname "${device_id_file}")"
  printf '\357\273\277%s' "${normalized_server_id}" > "${device_id_file}"
}

mkdir -p "${config_root}" "${data_root}" "${runtime_plugins_dir}" "$(dirname "${database_config}")"

copy_source_dirs "${config_root}" "${config_source_dirs}"
copy_source_dirs "${data_root}" "${data_source_dirs}"
link_shared_data_paths
disable_trickplay_and_chapter_image_options
write_server_id_file

if [ -d "${image_plugins_dir}" ]; then
  declare -A baked_plugins=()

  while IFS= read -r -d '' image_plugin_dir; do
    plugin_name="$(basename "${image_plugin_dir}")"
    runtime_plugin_dir="${runtime_plugins_dir}/${plugin_name}"
    baked_plugins["${plugin_name}"]=1
    rm -rf "${runtime_plugin_dir}"
    mkdir -p "${runtime_plugin_dir}"
    cp -R "${image_plugin_dir}/." "${runtime_plugin_dir}/"
  done < <(find "${image_plugins_dir}" -mindepth 1 -maxdepth 1 -type d -print0)

  if [ "${JELLYFIN_PRUNE_RUNTIME_PLUGINS:-true}" = "true" ]; then
    while IFS= read -r -d '' runtime_plugin_dir; do
      plugin_name="$(basename "${runtime_plugin_dir}")"
      if [ "${plugin_name}" = "configurations" ]; then
        continue
      fi
      if [ -z "${baked_plugins[$plugin_name]:-}" ]; then
        rm -rf "${runtime_plugin_dir}"
      fi
    done < <(find "${runtime_plugins_dir}" -mindepth 1 -maxdepth 1 -type d -print0)
  fi
fi

copy_source_dirs "${runtime_plugins_dir}/configurations" "${plugin_config_source_dirs}"
patch_jellyfin_enhanced_auto_skip_outro

if [ ! -f "${database_config}" ]; then
  write_postgres_database_config
fi

configured_plugin_name="$(
  xmlstarlet select \
    -t \
    -m '//DatabaseConfigurationOptions/CustomProviderOptions/PluginName' \
    -v . \
    -n \
    "${database_config}" 2>/dev/null || true
)"

if [ "${configured_plugin_name}" != "PostgreSQL" ]; then
  sqlite_backup="${database_config}.sqlite-provider-backup"
  if [ ! -f "${sqlite_backup}" ]; then
    cp "${database_config}" "${sqlite_backup}"
  fi
  write_postgres_database_config
fi

connection_string="Password=${POSTGRES_PASSWORD};User ID=${POSTGRES_USER};Host=${POSTGRES_HOST};Port=${POSTGRES_PORT};Database=${POSTGRES_DB}"

if [ -n "${POSTGRES_SSLMODE:-}" ]; then
  connection_string="${connection_string};SSL Mode=${POSTGRES_SSLMODE}"
fi

if [ -n "${POSTGRES_TRUSTSERVERCERTIFICATE:-}" ]; then
  connection_string="${connection_string};Trust Server Certificate=${POSTGRES_TRUSTSERVERCERTIFICATE}"
fi

xmlstarlet edit \
  --inplace \
  -u '//DatabaseConfigurationOptions/CustomProviderOptions/ConnectionString' \
  -v "${connection_string}" \
  "${database_config}"

if is_true "${JELLYFIN_ACTIVE_PASSIVE_ENABLED:-false}"; then
  lease_name="${JELLYFIN_LEASE_NAME:-jellyfin-active}"
  lease_namespace="${JELLYFIN_LEASE_NAMESPACE:-$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace 2>/dev/null || true)}"
  lease_identity="${JELLYFIN_LEASE_IDENTITY:-${HOSTNAME:-jellyfin-unknown}}"
  pod_name="${JELLYFIN_POD_NAME:-${HOSTNAME:-}}"
  pod_active_label_enabled="${JELLYFIN_ACTIVE_LABEL_ENABLED:-false}"
  pod_active_label_key="${JELLYFIN_ACTIVE_LABEL_KEY:-home-lab.io/jellyfin-active}"
  pod_active_label_value="${JELLYFIN_ACTIVE_LABEL_VALUE:-true}"
  lease_duration_seconds="${JELLYFIN_LEASE_DURATION_SECONDS:-30}"
  lease_renew_seconds="${JELLYFIN_LEASE_RENEW_SECONDS:-5}"
  lease_retry_seconds="${JELLYFIN_LEASE_RETRY_SECONDS:-5}"
  lease_renew_failure_limit="${JELLYFIN_LEASE_RENEW_FAILURE_LIMIT:-3}"
  kube_token_file="${KUBERNETES_SERVICEACCOUNT_TOKEN_FILE:-/var/run/secrets/kubernetes.io/serviceaccount/token}"
  kube_ca_file="${KUBERNETES_SERVICEACCOUNT_CA_FILE:-/var/run/secrets/kubernetes.io/serviceaccount/ca.crt}"
  kube_connect_timeout="${KUBERNETES_CONNECT_TIMEOUT_SECONDS:-3}"
  kube_request_timeout="${KUBERNETES_REQUEST_TIMEOUT_SECONDS:-10}"
  k8s_response_file="$(mktemp)"
  kube_api="https://${KUBERNETES_SERVICE_HOST:-}:${KUBERNETES_SERVICE_PORT_HTTPS:-443}"

  if [ -z "${lease_namespace}" ] || [ ! -r "${kube_token_file}" ] || [ ! -r "${kube_ca_file}" ] || [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
    echo "JELLYFIN_ACTIVE_PASSIVE_ENABLED requires a mounted Kubernetes service account token and API service environment" >&2
    exit 11
  fi

  run_jellyfin_with_lease "$@"
else
  mkdir -p "${ha_state_dir}"
  touch "${ha_alive_file}" "${ha_active_file}"
  exec /jellyfin/jellyfin "$@"
fi
