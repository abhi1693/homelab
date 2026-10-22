# PostgreSQL Pooler Disruption Budgets

This Fleet bundle owns disruption budgets for the listed CNPG poolers in the
`postgresql` namespace. Each budget selects its pooler by `cnpg.io/poolerName`.

The Kitchen and Launchboard applications and their dedicated poolers are shut
down. Their PDBs are omitted from `pdb.yaml` while the poolers have zero
instances; even a budget with `minAvailable: 0` produces `NoPods` events when no
pods match. Existing events
can remain until Kubernetes expires them after the PDB is removed.

When resuming Kitchen, restore its dedicated PDB with
`minAvailable: 1` and selector
`cnpg.io/poolerName: postgresql-pooler-hyperlocal-kitchen-rw` together with the
two pooler instances. Follow the application
[resumption procedure](../../../applications/apps/hyperlocal-kitchen/README.md#shutdown-state).

When resuming Launchboard, restore its dedicated PDB with `minAvailable: 1` and
selector `cnpg.io/poolerName: postgresql-pooler-launchboard-rw` together with its
two pooler instances. Follow its
[resumption procedure](../../../applications/apps/launchboard/README.md#shutdown-state).
The other pooler budgets retain their existing settings.
