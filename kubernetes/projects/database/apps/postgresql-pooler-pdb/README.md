# PostgreSQL Pooler Disruption Budgets

This Fleet bundle owns disruption budgets for the listed CNPG poolers in the
`postgresql` namespace. Each budget selects its pooler by `cnpg.io/poolerName`.

The other pooler budgets retain their existing settings.

Wardn License is also operator-paused. Its dedicated pooler budget is omitted
while `wardn-license-rw` has zero instances. Restore `minAvailable: 1` with selector
`cnpg.io/poolerName: postgresql-pooler-wardn-license-rw` together with its two
pooler instances when the application is explicitly resumed.
