# syntax=docker/dockerfile:1.7

ARG BASE_IMAGE=codercom/enterprise-base:ubuntu-20260223
FROM ${BASE_IMAGE}

ARG BASE_IMAGE
ARG TARGETARCH
ARG CODEX_NODE_MAJOR=22
ARG CODEX_PACKAGE=@openai/codex

LABEL org.opencontainers.image.base.name="${BASE_IMAGE}"
LABEL org.opencontainers.image.source="https://github.com/abhi1693/home-lab"
LABEL org.opencontainers.image.description="ARM64 Coder headless base image with common workspace tooling and Codex"

USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG DEBIAN_FRONTEND=noninteractive
ENV CODER_CLIENT_TLS_CA_FILE=/usr/local/share/ca-certificates/coder-home-ca.crt
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/coder-home-ca.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

RUN if [ "${TARGETARCH}" != "arm64" ]; then \
      echo "Unsupported TARGETARCH: ${TARGETARCH:-unset}; build with --platform linux/arm64" >&2; \
      exit 1; \
    fi

RUN apt-get update -yq \
  && apt-get install -yq --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    gnupg \
    jq \
    libssl-dev \
    pkg-config \
    python3 \
    zsh \
  && rm -rf /var/lib/apt/lists/*

COPY coder/templates/base/image/coder-home-ca.crt /usr/local/share/ca-certificates/coder-home-ca.crt

RUN update-ca-certificates

COPY --chmod=0755 coder/templates/base/image/install-node /usr/local/bin/install-node

RUN install-node "${CODEX_NODE_MAJOR}" \
  && npm install -g --prefix /opt/codex "${CODEX_PACKAGE}" \
  && ln -sf /opt/codex/bin/codex /usr/local/bin/codex \
  && chmod -R a+rX /opt/codex \
  && npm cache clean --force \
  && apt-get purge -yq nodejs \
  && apt-get autoremove -yq \
  && rm -rf /var/lib/apt/lists/* /root/.npm

RUN if id coder >/dev/null 2>&1; then \
      printf 'coder ALL=(ALL) NOPASSWD:ALL\n' >/etc/sudoers.d/coder \
      && chmod 0440 /etc/sudoers.d/coder \
      && chsh -s /usr/bin/zsh coder; \
    fi

USER coder
WORKDIR /home/coder
