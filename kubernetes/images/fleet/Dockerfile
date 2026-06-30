# syntax=docker/dockerfile:1.7

ARG FLEET_REF=v0.15.3

FROM --platform=$BUILDPLATFORM golang:1.25-bookworm AS build
ARG FLEET_REF
ARG TARGETOS
ARG TARGETARCH

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates git; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src

RUN set -eux; \
    git clone --depth 1 --branch "${FLEET_REF}" https://github.com/rancher/fleet.git .

COPY patches/ /tmp/fleet-patches/

RUN set -eux; \
    git apply /tmp/fleet-patches/*.patch

RUN set -eux; \
    CGO_ENABLED=0 GOWORK=off GOOS="${TARGETOS}" GOARCH="${TARGETARCH}" \
      go build \
        -ldflags "-w -s -X github.com/rancher/fleet/pkg/version.Version=${FLEET_REF}" \
        -o /out/fleetcontroller \
        ./cmd/fleetcontroller; \
    CGO_ENABLED=0 GOWORK=off GOOS="${TARGETOS}" GOARCH="${TARGETARCH}" \
      go build \
        -ldflags "-w -s -X github.com/rancher/fleet/pkg/version.Version=${FLEET_REF}" \
        -o /out/fleet \
        ./cmd/fleetcli

FROM registry.suse.com/bci/bci-base:15.7

COPY --from=build /src/package/log.sh /usr/bin/log.sh

RUN set -eux; \
    zypper rm -y container-suseconnect; \
    zypper ar --priority=500 https://download.opensuse.org/repositories/Virtualization:containers/5.5/Virtualization:containers.repo; \
    zypper --gpg-auto-import-keys ref; \
    zypper -n update; \
    zypper -n install --no-recommends openssh-clients tini git-core; \
    zypper -n clean -a; \
    rm -fr /var/log/zypp* /usr/share/doc

COPY --from=build /out/fleetcontroller /usr/bin/fleetcontroller
COPY --from=build /out/fleet /usr/bin/fleet

RUN useradd -u 1000 user

USER 1000
ENTRYPOINT ["tini", "--"]
CMD ["fleetcontroller"]
