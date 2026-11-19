ARG NETBOX_IMAGE=ghcr.io/netbox-community/netbox:v4.7.5@sha256:a521748a89c8966565bbf7832fd01caef2a122f46a21ccf7a7b7682dd3428839
FROM ${NETBOX_IMAGE}

COPY required-plugins.txt /tmp/required-plugins.txt
COPY verify_plugins.py /tmp/verify_plugins.py
COPY plugins.py /etc/netbox/config/plugins.py

RUN set -eux; \
    uv pip freeze --python /opt/netbox/venv/bin/python > /tmp/base-constraints.txt; \
    uv pip install --python /opt/netbox/venv/bin/python --no-cache \
      --constraint /tmp/base-constraints.txt -r /tmp/required-plugins.txt; \
    DEBUG=true \
      SECRET_KEY=dummyKeyWithMinimumLength------------------------- \
      /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py collectstatic --no-input; \
    test -s /opt/netbox/netbox/static/netbox_topology_views/css/app.css; \
    test -s /opt/netbox/netbox/static/netbox_topology_views/js/app.js; \
    /opt/netbox/venv/bin/python /tmp/verify_plugins.py /tmp/required-plugins.txt; \
    rm /tmp/required-plugins.txt /tmp/base-constraints.txt /tmp/verify_plugins.py
