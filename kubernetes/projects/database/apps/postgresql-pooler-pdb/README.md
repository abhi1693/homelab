# PostgreSQL Pooler Disruption Budgets

This Fleet bundle owns disruption budgets for the listed CNPG poolers in the
`postgresql` namespace. Each budget selects its pooler by `cnpg.io/poolerName`.

The [retired applications](../../../../../docs/runbooks/2026-10-28-app-retirements.md) have no dedicated pooler or disruption budget. Their database retention is documented in the [PostgreSQL bundle](../postgresql/README.md).
