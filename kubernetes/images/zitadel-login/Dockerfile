FROM node:26.13.1-bookworm@sha256:b7087bc4d973034b30854b378ba107f9fab622b47514cb7e2592e41b8bab8d49 AS build
ARG ZITADEL_REF=8afa5dd37a8e723efb9eace8d09fd5c1cccef694
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl --fail --location --retry 3 "https://codeload.github.com/zitadel/zitadel/tar.gz/${ZITADEL_REF}" | tar -xz --strip-components=1
RUN npm install --global pnpm@10.30.3
COPY patch-register.py /tmp/patch-register.py
COPY retry-not-found.ts retry-not-found.test.ts apps/login/src/lib/server/
RUN python3 /tmp/patch-register.py
ENV NX_DAEMON=false NX_NO_CLOUD=true NEXT_TELEMETRY_DISABLED=1
COPY pnpm-workspace.yaml pnpm-lock.yaml ./
COPY check-dependency-policy.py dependency-policy.json /tmp/
RUN python3 /tmp/check-dependency-policy.py --workspace /src/pnpm-workspace.yaml --lockfile /src/pnpm-lock.yaml --policy /tmp/dependency-policy.json
RUN pnpm install --frozen-lockfile
RUN pnpm nx run @zitadel/login:build
RUN cd apps/login && pnpm exec vitest run src/lib/server/retry-not-found.test.ts

FROM node:26.13.1-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5
WORKDIR /app
RUN apk upgrade --no-cache && \
    rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack && \
    addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs && \
    mkdir -p /.env-file && touch /.env-file/.env && chown -R nextjs:nodejs /.env-file
COPY --from=build --chown=1001:1001 /src/apps/login/.next/standalone/ /app/
USER nextjs
ENV HOSTNAME="::" PORT="3000" NODE_ENV="production" \
    NODE_OPTIONS="--use-openssl-ca --require /app/load-ssl-cert-dir.cjs" \
    SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt" ZITADEL_TLS_ENABLED="false" \
    OTEL_SERVICE_NAME="zitadel-login" OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["/usr/local/bin/node", "/app/healthcheck.mjs", "/ui/v2/login/ready"]
ENTRYPOINT ["/app/entrypoint.sh", "node", "apps/login/server.js"]
