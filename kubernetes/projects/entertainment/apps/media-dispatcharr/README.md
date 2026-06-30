# Dispatcharr

Dispatcharr replaces IPTV Tunerr as the IPTV manager and Jellyfin Live TV
source.

The web UI is available at `http://dispatcharr.media.home`.

## First-run setup

1. Open `http://dispatcharr.media.home` and create the admin account.
2. In M3U & EPG Manager, add the public India playlist:
   - Name: `IPTV India`
   - Account type: `Standard M3U`
   - URL: `https://iptv-org.github.io/iptv/countries/in.m3u`
3. Add the XMLTV guide:
   - Name: `IPTV India EPG`
   - URL: `https://iptv-epg.org/files/epg-in.xml`
4. Create or refresh the `EPG` channel profile so only channels with current
   XMLTV program rows and a passing stream probe are enabled. Channels with
   zero EPG program rows or dead upstream streams remain present in Dispatcharr
   but are disabled from Jellyfin's profile output.
5. In Jellyfin, use Dispatcharr's filtered output URLs:
   - HDHomeRun tuner: `http://dispatcharr.media.svc.cluster.local:9191/hdhr/EPG`
   - XMLTV guide: `http://dispatcharr.media.svc.cluster.local:9191/output/epg/EPG`

Dispatcharr runs in modular mode because the bundled AIO Redis binary crashes
on the Raspberry Pi kernel's 16 KiB page size. The web and Celery containers
share `dispatcharr-data`; PostgreSQL is provided by the shared CNPG cluster
through `postgresql-pooler-dispatcharr-rw.postgresql.svc.cluster.local`; Redis
is ephemeral.
