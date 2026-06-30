# syntax=docker/dockerfile:1.7

ARG POSTGRES_PROVIDER_REF=10.11.8-1
ARG JELLYFIN_IMAGE=jellyfin/jellyfin:10.11.8

FROM --platform=$BUILDPLATFORM alpine:3.22 AS plugin-download

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

FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:9.0 AS postgres-provider-build
ARG POSTGRES_PROVIDER_REF

COPY patches/ /tmp/jellyfin-patches/

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates git; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src

RUN set -eux; \
    git clone --depth 1 --recurse-submodules --shallow-submodules \
      --branch "${POSTGRES_PROVIDER_REF}" \
      https://github.com/JPVenson/Jellyfin.Pgsql.git .

RUN set -eux; \
    cd /src/jellyfin; \
    git apply --unidiff-zero /tmp/jellyfin-patches/*.patch

RUN dotnet restore Jellyfin.Plugin.Pgsql.sln
RUN dotnet restore jellyfin/Jellyfin.Server.Implementations/Jellyfin.Server.Implementations.csproj
RUN dotnet publish Jellyfin.Plugin.Pgsql.sln \
    --configuration Release \
    --no-restore \
    --output /app/publish
RUN dotnet build jellyfin/Jellyfin.Server.Implementations/Jellyfin.Server.Implementations.csproj \
    --configuration Release \
    --no-restore

FROM ${JELLYFIN_IMAGE}

USER root

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl jq postgresql-client xmlstarlet yt-dlp; \
    ln -sf /usr/bin/yt-dlp /usr/local/bin/youtube-dl; \
    rm -rf /opt/jellyfin/plugins; \
    mkdir -p /opt/jellyfin/plugins; \
    rm -rf /var/lib/apt/lists/*

COPY --from=plugin-download /opt/jellyfin/plugins/ /opt/jellyfin/plugins/
COPY --from=postgres-provider-build /app/publish/ /opt/jellyfin/plugins/PostgreSQL/
COPY --from=postgres-provider-build /src/jellyfin/Jellyfin.Server.Implementations/bin/Release/net9.0/Jellyfin.Server.Implementations.dll /jellyfin/Jellyfin.Server.Implementations.dll
COPY --from=postgres-provider-build /src/jellyfin/Jellyfin.Server.Implementations/bin/Release/net9.0/Jellyfin.Server.Implementations.pdb /jellyfin/Jellyfin.Server.Implementations.pdb
COPY entrypoint.sh /entrypoint.sh

RUN set -eux; \
    chmod 0755 /entrypoint.sh; \
    chmod -R a+rX /opt/jellyfin

ENTRYPOINT ["/entrypoint.sh"]
