FROM ghcr.io/netbox-community/netbox:v4.7.5@sha256:6cae589eeac232b9cda701d7672e9f232308063c5ec8e4b51b1afc7f59161b05
COPY plugins.py /etc/netbox/config/plugins.py
RUN uv pip freeze --python /opt/netbox/venv/bin/python > /tmp/base-constraints.txt && \
    uv pip install --python /opt/netbox/venv/bin/python --no-cache \
      --constraint /tmp/base-constraints.txt netbox-plugin-dns==1.7.3 netboxlabs-netbox-branching==1.2.3 && \
    DEBUG=true SECRET_KEY=temporary-build-only-key-for-django-static-collection-123456 \
      /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py collectstatic --no-input && \
    rm /tmp/base-constraints.txt
