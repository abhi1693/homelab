# ZITADEL

ZITADEL is the central identity provider for cluster applications.

- External issuer: `https://auth.abhimanyu-saharan.com`
- Ingress class: `cloudflare-tunnel`
- Database: shared CNPG PostgreSQL through `postgresql-pooler-zitadel-rw`
- Secrets: SOPS-managed `zitadel-masterkey`, `zitadel-env`, and `zitadel-postgresql`

## App Integration Contract

Applications should integrate with ZITADEL as separate OIDC or SAML clients in
ZITADEL. Do not share one OAuth client secret across apps. Each application gets
its own redirect URIs, allowed grant types, scopes, and token settings.

Use the issuer URL:

```text
https://auth.abhimanyu-saharan.com
```

OIDC discovery is expected at:

```text
https://auth.abhimanyu-saharan.com/.well-known/openid-configuration
```

The initial admin human username is `admin` with email
`admin@abhimanyu-saharan.com`; the bootstrap password is stored only in the
SOPS-managed `zitadel-env` secret and must be changed at first login.

The ZITADEL master key is intentionally stored in `zitadel-masterkey`. Losing
that key makes encrypted ZITADEL data unrecoverable.
