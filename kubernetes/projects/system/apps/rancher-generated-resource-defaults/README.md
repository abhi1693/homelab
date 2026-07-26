# Rancher Generated Resource Defaults

This bundle adds narrow namespace `LimitRange` defaults for workloads generated
by Rancher, Fleet, CAPI, and Rancher Monitoring charts that do not expose a
container resource-values interface.

The defaults apply only when a generated container omits a resource key. They
therefore leave explicitly sized Rancher and monitoring containers unchanged.
CPU limits are used in the small controller-only namespaces; the shared Fleet
and monitoring namespaces default requests and memory limits without imposing a
generic CPU throttle.

Do not extend this pattern to `longhorn-system`. Longhorn instance managers and
share managers are dynamically sized storage datapath workloads, and a single
namespace default would either under-size those processes or reserve excessive
memory for every Longhorn sidecar.
