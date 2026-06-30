# Firefly III Data Importer

Firefly III Data Importer runs as an internal Applications project app in the
`finance` namespace.

## Access

- Internal URL: `http://import.finance.home`
- Ingress class: `traefik`
- Service port: `8080`

## Firefly Connection

The importer reaches Firefly III through the in-cluster service URL
`http://firefly-iii:8080`. Browser-facing links back to Firefly use
`http://finance.home`.

The importer is deployed without a preconfigured Firefly Personal Access Token
or OAuth client ID. Create an OAuth client or token in Firefly III, then follow
the importer UI to connect it.

## Storage

Importer JSON configuration files are persisted under
`/var/www/html/storage/configurations` on the
`firefly-iii-data-importer-config` Longhorn PVC. The claim starts at `256Mi`.
