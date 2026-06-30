# syntax=docker/dockerfile:1.7

ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG BASE_IMAGE
ARG TARGETARCH
ARG NODE_MAJOR=22

LABEL org.opencontainers.image.base.name="${BASE_IMAGE}"
LABEL org.opencontainers.image.source="https://github.com/abhi1693/home-lab"
LABEL org.opencontainers.image.description="ARM64 Coder NetBox 4.6 workspace image with Python 3.12, Node.js, Codex, and uv"

USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG DEBIAN_FRONTEND=noninteractive

RUN if [ "${TARGETARCH}" != "arm64" ]; then \
      echo "Unsupported TARGETARCH: ${TARGETARCH:-unset}; build with --platform linux/arm64" >&2; \
      exit 1; \
    fi

RUN apt-get update -yq \
  && apt-get install -yq --no-install-recommends \
    graphviz \
    libcairo2 \
    libffi-dev \
    libfreetype-dev \
    libjpeg-dev \
    liblcms2-dev \
    libldap2-dev \
    libpq-dev \
    libsasl2-dev \
    libwebp-dev \
    libxml2-dev \
    libxslt1-dev \
    libyaml-dev \
    pipx \
    postgresql-client \
    python-is-python3 \
    python3.12-dev \
    python3-dev \
    python3-pip \
    python3-venv \
    tk-dev \
  && rm -rf /var/lib/apt/lists/*

RUN install-node "${NODE_MAJOR}"

RUN curl -LsSf --retry 5 --retry-all-errors --retry-delay 2 --connect-timeout 15 --max-time 180 \
    https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh \
  && chmod 0755 /usr/local/bin/uv /usr/local/bin/uvx

USER coder
WORKDIR /home/coder
