ARG NETBOX_IMAGE=ghcr.io/netbox-community/netbox:v4.6.3
FROM ${NETBOX_IMAGE}

COPY required-plugins.txt /tmp/required-plugins.txt

RUN set -eux; \
    uv pip install --python /opt/netbox/venv/bin/python --no-cache -r /tmp/required-plugins.txt; \
    mkdir -p /opt/netbox/netbox/static/netbox_topology_views/img; \
    /opt/netbox/venv/bin/python -c 'from netbox_metatype_importer import config; assert config.min_version == "4.6.0"; assert config.max_version == "4.6.99"; import netbox_topology_views, netbox_dns, netbox_lifecycle, netbox_bgp'; \
    rm /tmp/required-plugins.txt
