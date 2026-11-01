# Solver worker configuration

The active solver configuration is maintained in
[the worker Deployment](../deployment-worker-solver.yaml) and
[its network policy](../networkpolicy-solver.yaml), both included by the parent
Kustomization. This directory is not a separate Fleet workload.

See [solver operation](../README.md#search-and-solver-operation) for provider
boundaries and retry behavior.
