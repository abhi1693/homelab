# Project GitRepos

Project GitRepos select local application directories through `spec.paths`,
using explicit paths or component globs. A new `fleet.yaml` or `dependsOn` entry
still needs a path that discovers it. Register the directory in the same change
that introduces its permanent resources. For a new dependency, reconcile that
prerequisite and its normal validation Job to Ready first, then introduce the
consumer dependency and application change. Both stages remain desired state;
no temporary scale, namespace staging or backup trigger is needed.

The registration regression checks every Git-tracked project application
`fleet.yaml` against the union of local home-lab GitRepos. Each app, including a
paused app or one with a dedicated parent, needs exactly one selection. Missing
paths, dangling registrations and overlapping explicit/glob paths fail. Sources
belonging to another repository cannot register local applications. Empty,
untracked directories left after retirement are not source or exceptions.

[Traditional Fleet discovery](https://fleet.rancher.io/explanations/gitrepo-content)
scans selected directories recursively and treats paths independently. The guard
supports this repository's literal and component-glob path patterns; escaped or
negated patterns require extending the check with a regression first.
Infrastructure CI watches all project application `fleet.yaml` files and the
parent GitRepo manifests. Existing backup tests continue to check dependency
ordering and storage safety separately.

```sh
python3 -m unittest discover -s kubernetes/fleet/fleet-project-gitrepos/tests -v
```

These registrations do not transfer Namespace, PSA-label or Secret ownership.
Follow the existing namespace ownership runbook for any actual namespace change.

Fleet v0.16.2 returns an ordinary error when a named prerequisite does not yet
exist, which uses an exponential retry delay capped at 1,000 seconds. An existing
but unready prerequisite uses the normal 15-second dependency check. Repeated
identical errors retain the condition timestamp, so that timestamp is not a
heartbeat; inspect current objects and agent logs before diagnosing a stale watch.
Allow the normal retry rather than adding an arbitrary generation or restart.
See the [versioned deployer implementation](https://github.com/rancher/fleet/blob/14b1cd93eea8772b3abcf1b3786c254233ac149a/internal/cmd/agent/deployer/deployer.go)
and [retry durations](https://github.com/rancher/fleet/blob/14b1cd93eea8772b3abcf1b3786c254233ac149a/pkg/durations/durations.go).
