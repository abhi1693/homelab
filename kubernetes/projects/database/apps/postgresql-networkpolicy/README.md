# PostgreSQL network policies

Each application can reach only its declared pooler on TCP 5432. Pooler egress
is restricted to database, DNS and Kubernetes control-plane dependencies.

Jellyfin now serves native SQLite. The temporary qualification client rule has
been removed; the original production rule and database remain for the retained
PostgreSQL rollback boundary. The Jellyfin runtime receives no PG credentials.
