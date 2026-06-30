# syntax=docker/dockerfile:1.7

ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG BASE_IMAGE
ARG TARGETARCH
ARG NODE_MAJOR=24
ARG PORTABLEDESKTOP_VERSION=v0.0.8

LABEL org.opencontainers.image.base.name="${BASE_IMAGE}"
LABEL org.opencontainers.image.source="https://github.com/abhi1693/home-lab"
LABEL org.opencontainers.image.description="ARM64 Coder Ubuntu desktop workspace image with XFCE, Portable Desktop, Node.js, and Codex"

USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG DEBIAN_FRONTEND=noninteractive
RUN if [ "${TARGETARCH}" != "arm64" ]; then \
      echo "Unsupported TARGETARCH: ${TARGETARCH:-unset}; build with --platform linux/arm64" >&2; \
      exit 1; \
    fi

RUN install-node "${NODE_MAJOR}"

ADD --chmod=0755 --checksum=sha256:749494fc13658a10da2201ed3ea58a858d78fe3fb445132f72dfd797d0d2191e \
  "https://github.com/coder/portabledesktop/releases/download/${PORTABLEDESKTOP_VERSION}/portabledesktop-linux-arm64" \
  /usr/local/bin/portabledesktop

USER coder
WORKDIR /home/coder
