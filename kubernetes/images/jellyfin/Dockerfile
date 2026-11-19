# syntax=docker/dockerfile:1.29

ARG RUNTIME_IMAGE=ubuntu:26.04@sha256:d66b366dac61b575bee2aef07e9c26e8070096fbe84a3d4d3eb0da069b5d76db
ARG JELLYFIN_IMAGE=jellyfin/jellyfin:12.4@sha256:fea863d0cd9ec445985d9c75fc6ed64e38a1d2766cf0c250a33d553f4fc1b771

FROM --platform=$BUILDPLATFORM alpine:3.24 AS plugin-download

COPY required-plugins.txt /tmp/required-plugins.txt
COPY required-plugin-metadata.json /tmp/required-plugin-metadata.json

RUN set -eux; \
    apk add --no-cache ca-certificates curl jq unzip; \
    mkdir -p /opt/jellyfin/plugins; \
    while IFS='|' read -r plugin_dir source_url checksum; do \
      case "${plugin_dir}" in ''|\#*) continue ;; esac; \
      archive=/tmp/plugin.zip; \
      curl -fsSL "${source_url}" -o "${archive}"; \
      case "${checksum}" in \
        sha256:*) echo "${checksum#sha256:}  ${archive}" | sha256sum -c - ;; \
        md5:*) echo "${checksum#md5:}  ${archive}" | md5sum -c - ;; \
        *) echo "Unsupported checksum for ${plugin_dir}: ${checksum}" >&2; exit 1 ;; \
      esac; \
      rm -rf "/opt/jellyfin/plugins/${plugin_dir}"; \
      mkdir -p "/opt/jellyfin/plugins/${plugin_dir}"; \
      unzip -q "${archive}" -d "/opt/jellyfin/plugins/${plugin_dir}"; \
      rm -f "${archive}"; \
    done < /tmp/required-plugins.txt; \
    jq -r 'keys[]' /tmp/required-plugin-metadata.json \
      | while IFS= read -r plugin_dir; do \
        jq --arg plugin_dir "${plugin_dir}" '.[$plugin_dir]' /tmp/required-plugin-metadata.json \
          > "/opt/jellyfin/plugins/${plugin_dir}/meta.json"; \
      done; \
    find /opt/jellyfin/plugins -name meta.json -print0 \
      | xargs -0 -I '{}' sh -c 'tmp="${1}.tmp"; jq ".autoUpdate = false" "$1" > "${tmp}"; mv "${tmp}" "$1"' sh '{}'

FROM ${JELLYFIN_IMAGE} AS upstream-server

FROM ${RUNTIME_IMAGE}
ARG TARGETARCH
USER root

RUN set -eux; \
    apt-get update; \
    apt-get upgrade -y; \
    apt-get install -y --no-install-recommends ca-certificates curl jq sqlite3 xmlstarlet fontconfig libicu78 libfontconfig1 libfreetype6 libjemalloc2; \
    case "${TARGETARCH}" in \
      arm64) ffmpeg_sha=8823595cb4323f6e1eea2ef4af7742e8ab4f1728ef52ab6552608b8ae873ca48 ;; \
      amd64) ffmpeg_sha=2f4cf15936625c4bb13ea8ea0e2f35536be7ecb84af83372ff5df45cd861576a ;; \
      *) exit 1 ;; \
    esac; \
    curl -fsSL "https://repo.jellyfin.org/ubuntu/pool/main/j/jellyfin-ffmpeg/jellyfin-ffmpeg8_8.1.3-1-resolute_${TARGETARCH}.deb" -o /tmp/jellyfin-ffmpeg.deb; \
    echo "${ffmpeg_sha}  /tmp/jellyfin-ffmpeg.deb" | sha256sum -c -; \
    apt-get install -y --no-install-recommends /tmp/jellyfin-ffmpeg.deb; \
    rm /tmp/jellyfin-ffmpeg.deb; \
    rm -rf /opt/jellyfin/plugins; \
    mkdir -p /opt/jellyfin/plugins; \
    rm -rf /var/lib/apt/lists/*

COPY --from=upstream-server /jellyfin/ /jellyfin/
COPY --from=upstream-server /usr/share/fonts/ /usr/share/fonts/
COPY --from=plugin-download /opt/jellyfin/plugins/ /opt/jellyfin/plugins/
COPY entrypoint.sh /entrypoint.sh

RUN set -eux; \
    chmod 0755 /entrypoint.sh; \
    chmod -R a+rX /opt/jellyfin

ENV JELLYFIN_CACHE_DIR=/cache \
    JELLYFIN_CONFIG_DIR=/config \
    JELLYFIN_DATA_DIR=/data \
    JELLYFIN_LOG_DIR=/logs \
    JELLYFIN_WEB_DIR=/jellyfin/jellyfin-web \
    JELLYFIN_FFMPEG=/usr/lib/jellyfin-ffmpeg/ffmpeg \
    LD_PRELOAD=libjemalloc.so.2 \
    MALLOC_TRIM_THRESHOLD_=131072 \
    HOME=/config
RUN fc-cache -f && mkdir -p /config /data /cache /logs && chown 568:568 /config /data /cache /logs
USER 568:568
ENTRYPOINT ["/entrypoint.sh"]
