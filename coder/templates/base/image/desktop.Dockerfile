# syntax=docker/dockerfile:1.7

ARG BASE_IMAGE=codercom/enterprise-desktop:ubuntu-noble-20260512
FROM ${BASE_IMAGE}

ARG BASE_IMAGE
ARG TARGETARCH
ARG CODEX_NODE_MAJOR=22
ARG CODEX_PACKAGE=@openai/codex

LABEL org.opencontainers.image.base.name="${BASE_IMAGE}"
LABEL org.opencontainers.image.source="https://github.com/abhi1693/home-lab"
LABEL org.opencontainers.image.description="ARM64 Coder desktop base image with XFCE dependencies and Codex"

USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG DEBIAN_FRONTEND=noninteractive
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
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
    adwaita-icon-theme \
    build-essential \
    ca-certificates \
    curl \
    dbus-x11 \
    desktop-file-utils \
    fonts-dejavu \
    fonts-noto-color-emoji \
    git \
    gnupg \
    hicolor-icon-theme \
    iproute2 \
    jq \
    less \
    libasound2t64 \
    libgbm1 \
    libgl1 \
    libgtk-3-0t64 \
    libnss3 \
    libxss1 \
    locales \
    mousepad \
    nano \
    openssh-client \
    pkg-config \
    procps \
    python3 \
    python3-pip \
    ristretto \
    shared-mime-info \
    sudo \
    tango-icon-theme \
    thunar \
    tumbler \
    x11-xserver-utils \
    xdg-utils \
    xfce4-panel \
    xfce4-session \
    xfce4-settings \
    xfce4-terminal \
    xfdesktop4 \
    xfwm4 \
    xterm \
    zsh \
  && locale-gen en_US.UTF-8 \
  && update-locale LANG=en_US.UTF-8 \
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
