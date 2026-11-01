# Worker maintenance with bounded application pauses

A healthy cluster can lack evacuation headroom. Before authorized maintenance,
inspect CPU, memory, Pod slots and actual scheduling constraints, including
PostgreSQL hostname anti-affinity. Aggregate free capacity alone does not prove
that workloads can move. Never bypass PDBs or borrow tainted control-plane capacity.

When the operator authorizes stopping non-essential applications, represent the
pause in Git and wait for Fleet convergence. Record original replicas, CronJob
suspension, PDB and recommendation settings. Pause dependent automation with its
application, and freeze its ApplicationProfile scaling so recommendation commits
cannot undo the pause. Preserve databases, PVCs, secrets and resource reservations.
Keep dependencies of running applications online.

Before a separately authorized drain or reboot, require healthy databases and
storage, Fleet desired/applied convergence and feasible scheduling. Longhorn uses
`block-for-eviction`; verify that no active or transitional replica remains on the
worker before taking it offline. A pause does not authorize node maintenance.

Restore recorded settings through scoped Git/Fleet changes, with databases and
poolers before applications, data-owning services before dependent automation,
and the recommendation controller last. Preserve unrelated operator holds and
backup, security and startup gates. Do not revert a whole historical commit.
Require readiness, bound PVCs, healthy storage, database recovery and Fleet
convergence before considering restoration complete.

The completed Ubuntu conversion and its application restoration evidence are
archived in [issue #168](https://github.com/abhi1693/home-lab/issues/168) and Git
history. They are not an active pause or maintenance procedure.
