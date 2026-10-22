# DevFeed identity migration

The old DevFeed organization `389593181982820082` uses
`https://auth.abhimanyu-saharan.com`. The dedicated DevFeed organization
`395926894337328224` uses `https://auth.devfeed.tech`.

The old preferred login name appends an organization domain to an email address.
Use the existing stored email as the new username and email, dropping only that
organization suffix. Do not use the literal two-`@` preferred login name as an
email address. Preserve verification state; return verification codes rather
than sending messages during import.

## Preparation

1. Export only the source DevFeed organization using ZITADEL's Admin export API.
   Store exports and mappings in a private directory outside Git, mode 0700,
   with files mode 0600. Include password hashes/OTP where present.
2. Import users through the User API into the existing target organization.
   Remap source GitHub/Google provider IDs to the configured target providers.
   Keep the external provider user IDs unchanged. Do not copy source projects
   over the target's configured Development and Production projects.
3. Reuse an existing target user only after matching external provider identities;
   an email match alone is insufficient. Persist an explicit one-to-one JSON map
   of old user IDs to new user IDs after every successful import.
4. Map source project role grants to the corresponding target project by name.
   Verify every source social link and role grant in the target.

The initial migration has 34 users and 36 GitHub/Google links, with no password
hashes or OTP secrets in the export. One target account already represented the
same external identities and was reused. Old identities remain intact.

## Database cutover

DevFeed has three identity stores: `user_accounts`, `partner_memberships` and
`admin_preferences`. User-account UUIDs must remain unchanged because reader
activity, follows, profiles and other application records reference them.
Administrator preference keys hash `[issuer, organization_id, subject]` and must
be recomputed. Partner membership keys also include the issuer and subject.

Use a local port-forward to PostgreSQL (read-only Kubernetes transport):

```sh
kubectl port-forward -n postgresql service/postgresql-rw 15439:5432
python3 scripts/migrate-devfeed-identities.py --mapping /private/path/user-map.json
```

The Python environment needs psycopg. The script reads the existing database
Secret without printing credentials. The default is a read-only plan.

Pause `devfeed-user-api`, `devfeed-admin-api` and `devfeed-partner-api` by
committing zero replicas through Fleet. Wait for all three to have no running
replicas. The public reader and content API remain available; account operations
are temporarily unavailable. Then run:

```sh
python3 scripts/migrate-devfeed-identities.py --mapping /private/path/user-map.json --apply
```

The script writes a private pre-cutover backup and changes all three identity
stores in one database transaction, under table locks and bounded timeouts. It
checks the old organization and the mapping, rejects target collisions and
reruns, and verifies that every non-identity field and account UUID is unchanged
before committing.

Update the application ConfigMaps to the target issuer, organization, clients
and social providers. Restore two API replicas through Fleet with an updated
pod-template revision. Existing browser sessions must require a fresh sign-in.
Verify Fleet desired/applied IDs, live environment, authorization redirects,
provider links, role grants, account UUIDs and dependent application data.

## Rollback

Keep the private mapping and `database-before-cutover.json` backup. Do not delete
source users during the rollback window. Pause the three APIs through Fleet,
reverse the identity triples and administrator preference hashes in a database
transaction using the backup, restore the old ConfigMaps, and resume the APIs
through Fleet. If the new instance accepted additional users or application data,
reconcile that delta first; do not restore entire tables over newer records.
