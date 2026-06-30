# syntax=docker/dockerfile:1.7

ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG BASE_IMAGE
ARG TARGETARCH
ARG NODE_MAJOR=26

LABEL org.opencontainers.image.base.name="${BASE_IMAGE}"
LABEL org.opencontainers.image.source="https://github.com/abhi1693/home-lab"
LABEL org.opencontainers.image.description="ARM64 Coder Node.js 26 workspace image with Codex"

USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG DEBIAN_FRONTEND=noninteractive

RUN if [ "${TARGETARCH}" != "arm64" ]; then \
      echo "Unsupported TARGETARCH: ${TARGETARCH:-unset}; build with --platform linux/arm64" >&2; \
      exit 1; \
    fi

RUN install-node "${NODE_MAJOR}"

USER coder
WORKDIR /home/coder
