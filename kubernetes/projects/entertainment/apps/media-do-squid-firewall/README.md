# DigitalOcean Proxy Firewall Updater

This app keeps the `squid-proxy-locked-down` DigitalOcean cloud firewall in sync
with the home cluster's current public IPv4 address. It runs every 15 minutes
and updates inbound proxy rules to the detected `/32`.

Managed ports:

- `3128/tcp`: Squid HTTP proxy
- `2525/tcp`: Postfix SMTP relay for Postal outbound delivery

The DigitalOcean API token is intentionally not stored in Git. The live cluster
must have this Secret:

```sh
kubectl -n media create secret generic digitalocean-api-token \
  --from-literal=token="$DO_API_TOKEN"
```
