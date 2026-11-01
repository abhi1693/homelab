# Rancher Generated Resource Defaults

This bundle adds narrow namespace `LimitRange` defaults for workloads generated
by Rancher, Fleet, CAPI, and Rancher Monitoring charts that do not expose a
container resource-values interface.

The defaults apply only when a generated container omits a resource key. They
therefore leave explicitly sized Rancher and monitoring containers unchanged.
CPU limits are used in the small controller-only namespaces; the shared Fleet
and monitoring namespaces default requests and memory limits without imposing a
generic CPU throttle.

`fleet-local` defaults to a 256Mi memory limit, a 32Mi memory request and a
250m CPU cap. Defaults apply only to newly admitted containers that omit the
corresponding resource key. Verify generated cleanup Jobs complete within these
bounds before changing the namespace policy.

Do not extend this pattern to `longhorn-system`. Longhorn instance managers and
share managers are dynamically sized storage datapath workloads, and a single
namespace default would either under-size those processes or reserve excessive
memory for every Longhorn sidecar.

The `cattle-fleet-local-system` Fleet agents default to a 1Gi memory cap,
448Mi memory request, 300m CPU request and one-core CPU cap. A kernel-recorded
Fleet-agent cgroup OOM at the former 768Mi cap was found during the 28 October
incident; sampled working sets missed that short burst. Apply the default
through Fleet, then replace agents serially under the authorized runtime
recovery procedure. Existing Pods retain their admitted limits until replaced.
