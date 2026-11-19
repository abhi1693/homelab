#!/usr/bin/env bash
set -euo pipefail
log() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; }
is_true() { case "${1:-}" in 1 | true | TRUE | yes | YES | on | ON) return 0 ;; *) return 1 ;; esac }
if [ "${1:-}" = healthcheck ]; then
  curl -fsS --max-time 3 http://127.0.0.1:8096/health > /dev/null
  exit
fi
export JELLYFIN_CONFIG_DIR=/config JELLYFIN_DATA_DIR=/data JELLYFIN_LOG_DIR=/logs
config_root=/config
data_root=/data
runtime_plugins_dir=/data/plugins
config_source_dirs=${JELLYFIN_CONFIG_SOURCE_DIRS:-}
data_source_dirs=${JELLYFIN_DATA_SOURCE_DIRS:-}
plugin_config_source_dirs=${JELLYFIN_PLUGIN_CONFIG_SOURCE_DIRS:-}
shared_data_dir=${JELLYFIN_SHARED_DATA_DIR:-}
shared_data_paths=${JELLYFIN_SHARED_DATA_PATHS:-}
server_id=${JELLYFIN_SERVER_ID:-}
device_id_file=/data/data/device.txt
if [ "${JELLYFIN_REQUIRE_MIGRATION_RECEIPT:-true}" = true ]; then
  test -s /data/data/jellyfin.db
  if [ "${JELLYFIN_QUALIFICATION:-false}" = true ]; then
    jq -e '.integrity == "ok"' /data/sqlite-migration.receipt.json > /dev/null
  else
    jq -e '.mode == "cutover" and .source_quiesced == true and .integrity == "ok"' /data/sqlite-migration.receipt.json > /dev/null
  fi
fi
copy_source_dirs() {
  local target_dir="$1"
  local source_dirs="$2"
  local destination_path
  local source_path

  IFS=':' read -r -a sources <<< "${source_dirs}"
  for source_dir in "${sources[@]}"; do
    if [ -d "${source_dir}" ]; then
      mkdir -p "${target_dir}"
      while IFS= read -r -d '' source_path; do
        destination_path="${target_dir}/$(basename "${source_path}")"
        if [ -d "${source_path}" ]; then
          mkdir -p "${destination_path}"
          cp -RL "${source_path}/." "${destination_path}/"
        else
          rm -f "${destination_path}"
          cp -L "${source_path}" "${destination_path}"
        fi
      done < <(
        find "${source_dir}" \
          -mindepth 1 \
          -maxdepth 1 \
          ! -name '..*' \
          -print0
      )
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
    1 | true | yes | on)
      normalized_value=true
      ;;
    0 | false | no | off)
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
    if [ "$(xmlstarlet select -t -v 'count(//*[local-name()="AutoSkipOutro"])' "${config_file}" 2> /dev/null || echo 0)" != "0" ]; then
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
    if jq -e 'type == "object" and (has("AutoSkipOutro") or has("autoSkipOutro"))' "${settings_file}" > /dev/null 2>&1; then
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
      '' | /* | *'..'*)
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
    if [ "$(xmlstarlet select -t -v 'count(//*[local-name()="EnableTrickplayImageExtraction"])' "${option_file}" 2> /dev/null || echo 0)" != "0" ]; then
      xmlstarlet edit \
        --inplace \
        -u '//*[local-name()="EnableTrickplayImageExtraction"]' \
        -v false \
        "${option_file}"
    fi

    if [ "$(xmlstarlet select -t -v 'count(//*[local-name()="ExtractTrickplayImagesDuringLibraryScan"])' "${option_file}" 2> /dev/null || echo 0)" != "0" ]; then
      xmlstarlet edit \
        --inplace \
        -u '//*[local-name()="ExtractTrickplayImagesDuringLibraryScan"]' \
        -v false \
        "${option_file}"
    fi

    if [ "$(xmlstarlet select -t -v 'count(//*[local-name()="EnableChapterImageExtraction"])' "${option_file}" 2> /dev/null || echo 0)" != "0" ]; then
      xmlstarlet edit \
        --inplace \
        -u '//*[local-name()="EnableChapterImageExtraction"]' \
        -v false \
        "${option_file}"
    fi

    if [ "$(xmlstarlet select -t -v 'count(//*[local-name()="ExtractChapterImagesDuringLibraryScan"])' "${option_file}" 2> /dev/null || echo 0)" != "0" ]; then
      xmlstarlet edit \
        --inplace \
        -u '//*[local-name()="ExtractChapterImagesDuringLibraryScan"]' \
        -v false \
        "${option_file}"
    fi

    log "Jellyfin library options: disabled trickplay and chapter image extraction in ${option_file}"
  done < <(find -L "${data_root}/root" -type f -name options.xml -print0)
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

mkdir -p /config /data/plugins/configurations /logs
copy_source_dirs "${config_root}" "${config_source_dirs}"
copy_source_dirs "${data_root}" "${data_source_dirs}"
link_shared_data_paths
disable_trickplay_and_chapter_image_options
write_server_id_file
# Plugin binaries are an explicit image lock; configurations remain persistent.
for plugin in /data/plugins/*; do
  [ -d "$plugin" ] || continue
  [ "$(basename "$plugin")" = configurations ] || rm -rf "$plugin"
done
for plugin in /opt/jellyfin/plugins/*; do
  [ -d "$plugin" ] || continue
  case "$(basename "$plugin")" in PostgreSQL | Intro\ Skipper_* | InPlayer\ Episode\ Preview_* | Playback\ Reporting_*) continue ;; esac
  cp -R "$plugin" /data/plugins/
done
copy_source_dirs /data/plugins/configurations "${plugin_config_source_dirs}"
patch_jellyfin_enhanced_auto_skip_outro
# A provider change is deliberate; never infer PostgreSQL from mounted secrets.
cat > /config/database.xml << 'XML'
<?xml version="1.0" encoding="utf-8"?>
<DatabaseConfigurationOptions><DatabaseType>Jellyfin-SQLite</DatabaseType><LockingBehavior>NoLock</LockingBehavior></DatabaseConfigurationOptions>
XML
mkdir -p /tmp/jellyfin-ha
touch /tmp/jellyfin-ha/wrapper-alive /tmp/jellyfin-ha/active
exec /jellyfin/jellyfin "$@"
