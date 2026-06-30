#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/safe-node-shutdown.sh <node-name>

Safely prepare and power off a Kubernetes node using the rack-ops
rpi-shutdown helper.

The script:
  - verifies the node exists and is Ready
  - refuses to shut down a control-plane/etcd node unless two other
    control-plane/etcd nodes are Ready
  - cordons the node
  - drains the node without forcing PDB violations
  - waits for Longhorn volumes to detach from the node
    except explicitly allowed one-replica PVCs
  - POSTs to rack-ops service rpi-shutdown-<node-name>/shutdown
  - waits for the node to report NotReady or become unreachable

Environment overrides:
  RACK_OPS_NAMESPACE        default: rack-ops
  SHUTDOWN_SERVICE_PREFIX   default: rpi-shutdown-
  DRAIN_TIMEOUT             default: 10m
  DRAIN_POD_SELECTOR        default: longhorn.io/component!=instance-manager
                            set empty to drain all non-DaemonSet pods
  DRAIN_SKIP_WAIT_FOR_DELETE_TIMEOUT
                            default: 60
                            seconds before drain stops waiting on already
                            deleting pods
  LONGHORN_DETACH_TIMEOUT   default: 300
  ALLOWED_ATTACHED_LONGHORN_PVCS
                            default: media/media-downloads
                            comma/space-separated namespace/pvc names that
                            may remain attached only when numberOfReplicas=1
  SHUTDOWN_WAIT_TIMEOUT     default: 180
  PORT_FORWARD_LOCAL_PORT   default: random 18000-18999
USAGE
}

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
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

node_is_control_plane_or_etcd() {
  local node=$1
  kubectl get node "$node" --show-labels --no-headers |
    grep -Eq 'node-role\.kubernetes\.io/(control-plane|master|etcd)'
}

ready_control_plane_or_etcd_nodes_excluding() {
  local excluded=$1
  local line name labels ready count=0

  while IFS= read -r line; do
    name=$(awk '{print $1}' <<<"$line")
    [[ "$name" == "$excluded" ]] && continue

    labels=$(awk '{print $NF}' <<<"$line")
    [[ "$labels" =~ node-role\.kubernetes\.io/(control-plane|master|etcd) ]] || continue

    ready=$(kubectl get node "$name" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)
    [[ "$ready" == "True" ]] && count=$((count + 1))
  done < <(kubectl get nodes --show-labels --no-headers)

  printf '%s\n' "$count"
}

allowed_attached_longhorn_pvc() {
  local namespace=$1
  local pvc=$2
  local allowed_pvcs=${ALLOWED_ATTACHED_LONGHORN_PVCS:-media/media-downloads}
  local allowed

  [[ -n "$namespace" && -n "$pvc" ]] || return 1

  allowed_pvcs=${allowed_pvcs//,/ }
  for allowed in $allowed_pvcs; do
    if [[ "$allowed" == "$namespace/$pvc" ]]; then
      return 0
    fi
  done

  return 1
}

longhorn_attached_volumes_for_node() {
  local node=$1

  if ! kubectl api-resources --api-group=longhorn.io 2>/dev/null | grep -q '^volumes'; then
    return
  fi

  kubectl -n longhorn-system get volumes.longhorn.io \
    -o jsonpath="{range .items[?(@.status.currentNodeID=='$node')]}{.metadata.name}{'\t'}{.status.kubernetesStatus.namespace}{'\t'}{.status.kubernetesStatus.pvcName}{'\t'}{.spec.numberOfReplicas}{'\n'}{end}"
}

longhorn_blocking_attached_count() {
  local node=$1
  local volume namespace pvc replicas count=0

  while IFS=$'\t' read -r volume namespace pvc replicas; do
    [[ -n "$volume" ]] || continue

    if [[ "$replicas" == "1" ]] && allowed_attached_longhorn_pvc "$namespace" "$pvc"; then
      continue
    fi

    count=$((count + 1))
  done < <(longhorn_attached_volumes_for_node "$node")

  printf '%s\n' "$count"
}

print_longhorn_attached() {
  local node=$1

  kubectl -n longhorn-system get volumes.longhorn.io \
    -o custom-columns='NAME:.metadata.name,PVC_NS:.status.kubernetesStatus.namespace,PVC:.status.kubernetesStatus.pvcName,REPLICAS:.spec.numberOfReplicas,STATE:.status.state,ROBUSTNESS:.status.robustness,NODE:.status.currentNodeID' |
    awk -v node="$node" 'NR == 1 || $NF == node'
}

print_allowed_longhorn_attached() {
  local node=$1
  local volume namespace pvc replicas printed=0

  while IFS=$'\t' read -r volume namespace pvc replicas; do
    [[ -n "$volume" ]] || continue

    if [[ "$replicas" == "1" ]] && allowed_attached_longhorn_pvc "$namespace" "$pvc"; then
      if (( printed == 0 )); then
        log "Allowing one-replica Longhorn PVC(s) to remain attached:"
        printed=1
      fi
      log "  $namespace/$pvc ($volume)"
    fi
  done < <(longhorn_attached_volumes_for_node "$node")
}

cleanup() {
  if [[ -n "${PORT_FORWARD_PID:-}" ]]; then
    kill "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
    wait "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${PORT_FORWARD_LOG:-}" ]]; then
    rm -f "$PORT_FORWARD_LOG"
  fi
}

main() {
  if [[ $# -ne 1 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
  fi

  need kubectl
  need curl

  local node=$1
  [[ "$node" =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid node name: $node"
  node=$(resolve_node_name "$node")

  local rack_ops_namespace=${RACK_OPS_NAMESPACE:-rack-ops}
  local service_prefix=${SHUTDOWN_SERVICE_PREFIX:-rpi-shutdown-}
  local service="${service_prefix}${node}"
  local drain_timeout=${DRAIN_TIMEOUT:-10m}
  local drain_pod_selector=${DRAIN_POD_SELECTOR-longhorn.io/component!=instance-manager}
  local drain_skip_wait_for_delete_timeout=${DRAIN_SKIP_WAIT_FOR_DELETE_TIMEOUT:-60}
  local detach_timeout=${LONGHORN_DETACH_TIMEOUT:-300}
  local shutdown_wait_timeout=${SHUTDOWN_WAIT_TIMEOUT:-180}
  local local_port=${PORT_FORWARD_LOCAL_PORT:-$((18000 + RANDOM % 1000))}
  PORT_FORWARD_LOG=$(mktemp -t safe-node-shutdown-port-forward.XXXXXX)

  trap cleanup EXIT

  log "Checking node $node"
  kubectl get node "$node" >/dev/null || die "node not found: $node"

  if ! is_node_ready "$node"; then
    die "node $node is not Ready; refusing to start shutdown workflow"
  fi

  if node_is_control_plane_or_etcd "$node"; then
    local ready_peers
    ready_peers=$(ready_control_plane_or_etcd_nodes_excluding "$node")
    if (( ready_peers < 2 )); then
      die "node $node is control-plane/etcd and only $ready_peers other control-plane/etcd node(s) are Ready"
    fi
    log "Control-plane/etcd quorum preflight passed: $ready_peers peer nodes are Ready"
  fi

  log "Checking shutdown helper service $rack_ops_namespace/$service"
  kubectl -n "$rack_ops_namespace" get service "$service" >/dev/null ||
    die "shutdown helper service not found: $rack_ops_namespace/$service"

  log "Cordoning $node"
  kubectl cordon "$node"

  log "Draining $node with PDBs respected"
  local drain_args=(
    "$node"
    --ignore-daemonsets \
    --delete-emptydir-data \
    --skip-wait-for-delete-timeout="$drain_skip_wait_for_delete_timeout" \
    --timeout="$drain_timeout"
  )
  if [[ -n "$drain_pod_selector" ]]; then
    drain_args+=(--pod-selector="$drain_pod_selector")
  fi
  kubectl drain "${drain_args[@]}"

  log "Waiting for Longhorn volumes to detach from $node"
  local elapsed=0
  local attached
  while true; do
    attached=$(longhorn_blocking_attached_count "$node")
    if [[ "$attached" == "0" ]]; then
      break
    fi

    if (( elapsed >= detach_timeout )); then
      print_longhorn_attached "$node" >&2
      die "timed out waiting for Longhorn volumes to detach from $node"
    fi

    sleep 10
    elapsed=$((elapsed + 10))
  done
  print_allowed_longhorn_attached "$node"

  if ! is_node_ready "$node"; then
    log "$node is already no longer Ready; shutdown request is not needed"
    return
  fi

  log "Opening port-forward to $rack_ops_namespace/$service"
  kubectl -n "$rack_ops_namespace" port-forward "svc/$service" "${local_port}:8000" >"$PORT_FORWARD_LOG" 2>&1 &
  PORT_FORWARD_PID=$!
  sleep 2

  if ! kill -0 "$PORT_FORWARD_PID" >/dev/null 2>&1; then
    cat "$PORT_FORWARD_LOG" >&2 || true
    die "port-forward failed"
  fi

  log "Requesting clean host shutdown for $node"
  curl -fsS -X POST "http://127.0.0.1:${local_port}/shutdown"
  printf '\n'

  log "Waiting for $node to become NotReady"
  elapsed=0
  while is_node_ready "$node"; do
    if (( elapsed >= shutdown_wait_timeout )); then
      die "shutdown request was accepted, but $node is still Ready after ${shutdown_wait_timeout}s"
    fi

    sleep 10
    elapsed=$((elapsed + 10))
  done

  log "$node is no longer Ready"
}

main "$@"
