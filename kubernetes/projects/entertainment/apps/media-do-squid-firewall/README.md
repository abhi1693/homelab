# DigitalOcean Proxy Firewall Updater

This app keeps the `squid-proxy-locked-down` DigitalOcean cloud firewall in sync
with the home cluster's current public IPv4 address. It runs every 15 minutes
and updates inbound proxy rules to the detected `/32`.

The CronJob retains at most one failed Job and expires terminal Jobs after 30
minutes. Repeated failures therefore remain visible through a newer Job, while
a recovered updater does not leave a stale `KubeJobFailed` alert behind.

Managed ports:

- `3128/tcp`: Squid HTTP proxy
- `2525/tcp`: Postfix SMTP relay for Postal outbound delivery

Prowlarr uses the Squid proxy for tagged public indexers. Ryokan uses the same
proxy as its external HTTPS egress so its built-in Nyaa scraper bypasses the
home ISP path. Ryokan's proxy URL and credentials are stored separately in the
SOPS-encrypted `media-ryokan/secrets.sops.yaml` manifest.

The DigitalOcean API token is intentionally not stored in Git. The live cluster
must have this Secret:

```sh
kubectl -n media create secret generic digitalocean-api-token \
  --from-literal=token="$DO_API_TOKEN"
```
