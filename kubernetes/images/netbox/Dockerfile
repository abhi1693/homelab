ARG NETBOX_IMAGE=ghcr.io/netbox-community/netbox:v4.6.9
FROM ${NETBOX_IMAGE}

COPY required-plugins.txt /tmp/required-plugins.txt
COPY plugins.py /etc/netbox/config/plugins.py

RUN set -eux; \
    uv pip install --python /opt/netbox/venv/bin/python --no-cache -r /tmp/required-plugins.txt; \
    DEBUG=true \
      SECRET_KEY=dummyKeyWithMinimumLength------------------------- \
      /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py collectstatic --no-input; \
    test -s /opt/netbox/netbox/static/netbox_topology_views/css/app.css; \
    test -s /opt/netbox/netbox/static/netbox_topology_views/css/vendor.css; \
    test -s /opt/netbox/netbox/static/netbox_topology_views/js/app.js; \
    /opt/netbox/venv/bin/python -c 'from netbox_metatype_importer import config; assert config.min_version == "4.6.0"; assert config.max_version == "4.6.99"; from netbox_custom_objects import config as custom_objects_config; assert custom_objects_config.version == "0.6.1"; assert custom_objects_config.min_version <= "4.6.9" <= custom_objects_config.max_version; import netbox_topology_views, netbox_dns, netbox_lifecycle'; \
    rm /tmp/required-plugins.txt
