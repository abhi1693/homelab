FROM node:26-bookworm AS build
ARG ZITADEL_REF=e2886a61670ca8fd41c9434f87036546e5620bcc
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl --fail --location --retry 3 "https://codeload.github.com/zitadel/zitadel/tar.gz/${ZITADEL_REF}" | tar -xz --strip-components=1
RUN corepack enable && corepack prepare pnpm@10.30.3 --activate
COPY patch-register.py /tmp/patch-register.py
COPY retry-not-found.ts retry-not-found.test.ts apps/login/src/lib/server/
RUN python3 /tmp/patch-register.py
ENV NX_DAEMON=false NX_NO_CLOUD=true NEXT_TELEMETRY_DISABLED=1
COPY pnpm-workspace.yaml pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
RUN pnpm nx run @zitadel/login:build
RUN cd apps/login && pnpm exec vitest run src/lib/server/retry-not-found.test.ts

FROM node:26-alpine
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
