#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/post-node-power-on.sh <node-name>

Prepare a powered-on Kubernetes node to receive workload again.

The script:
  - accepts short Raspberry Pi aliases like rpi2 for k8s-rpi2
  - waits for the node to become Ready
  - uncordons the node
  - waits for node-local system pods to settle
  - prints current pod distribution by node

This script does not delete, evict, or restart pods. Kubernetes will schedule
future or recreated pods onto the uncordoned node, but it does not automatically
move already-running pods just because a node came back.

Environment overrides:
  NODE_READY_TIMEOUT        default: 600 seconds
  SYSTEM_PODS_READY_TIMEOUT default: 300 seconds
  SYSTEM_NAMESPACES_REGEX   default: ^(kube-system|longhorn-system|cattle-monitoring-system|rack-ops)$
USAGE
}

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

warn() {
  printf '[%s] warning: %s\n' "$(date '+%H:%M:%S')" "$*" >&2
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

resolve_node_name() {
  local node=$1
  local prefixed_node="k8s-$node"

  if kubectl get node "$node" >/dev/null 2>&1; then
    printf '%s\n' "$node"
    return
  fi

  if [[ "$node" != k8s-* ]] && kubectl get node "$prefixed_node" >/dev/null 2>&1; then
    log "Resolved node alias $node to $prefixed_node" >&2
    printf '%s\n' "$prefixed_node"
    return
  fi

  die "node not found: $node"
}

is_node_ready() {
  local node=$1
  local ready
  ready=$(kubectl get node "$node" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)
  [[ "$ready" == "True" ]]
}

wait_for_node_ready() {
  local node=$1
  local timeout=$2
  local elapsed=0

  while ! is_node_ready "$node"; do
    if (( elapsed >= timeout )); then
      kubectl get node "$node" -o wide >&2 || true
      die "timed out waiting for $node to become Ready"
    fi

    sleep 10
    elapsed=$((elapsed + 10))
  done
}

not_ready_system_pods_on_node() {
  local node=$1
  local namespace_regex=$2

  kubectl get pods -A --field-selector "spec.nodeName=$node" --no-headers 2>/dev/null |
    awk -v ns_regex="$namespace_regex" '
      $1 !~ ns_regex { next }
      $4 == "Completed" { next }
      $4 == "Running" {
        split($3, ready, "/")
        if (ready[1] == ready[2]) {
          next
        }
      }
      {
        print $1 "/" $2 " ready=" $3 " status=" $4
      }
    '
}

wait_for_system_pods() {
  local node=$1
  local timeout=$2
  local namespace_regex=$3
  local elapsed=0
  local not_ready

  while true; do
    not_ready=$(not_ready_system_pods_on_node "$node" "$namespace_regex")
    if [[ -z "$not_ready" ]]; then
      return
    fi

    if (( elapsed >= timeout )); then
      warn "system pods on $node did not all become Ready before timeout"
      printf '%s\n' "$not_ready" >&2
      return
    fi

    sleep 10
    elapsed=$((elapsed + 10))
  done
}

print_pod_distribution() {
  kubectl get pods -A -o wide --no-headers |
    awk '
      $4 == "Running" && $8 != "<none>" {
        count[$8]++
      }
      END {
        printf "%-24s %s\n", "NODE", "RUNNING_PODS"
        for (node in count) {
          printf "%-24s %d\n", node, count[node]
        }
      }
    ' |
    sort
}

main() {
  if [[ $# -ne 1 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
  fi

  need kubectl

  local node=$1
  [[ "$node" =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid node name: $node"
  node=$(resolve_node_name "$node")

  local node_ready_timeout=${NODE_READY_TIMEOUT:-600}
  local system_pods_ready_timeout=${SYSTEM_PODS_READY_TIMEOUT:-300}
  local system_namespaces_regex=${SYSTEM_NAMESPACES_REGEX:-'^(kube-system|longhorn-system|cattle-monitoring-system|rack-ops)$'}

  log "Waiting for $node to become Ready"
  wait_for_node_ready "$node" "$node_ready_timeout"

  log "Uncordoning $node"
  kubectl uncordon "$node"

  log "Waiting for node-local system pods on $node"
  wait_for_system_pods "$node" "$system_pods_ready_timeout" "$system_namespaces_regex"

  log "Node status"
  kubectl get node "$node" -o wide

  log "Pods currently on $node"
  kubectl get pods -A -o wide --field-selector "spec.nodeName=$node"

  log "Running pod distribution by node"
  print_pod_distribution
}

main "$@"
