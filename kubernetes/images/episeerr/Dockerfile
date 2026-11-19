# syntax=docker/dockerfile:1.29

ARG EPISEERR_IMAGE=docker.io/vansmak/episeerr:4.0.12@sha256:75c721c7e6ccc72e823bd76d694b97e754913f4ea0cc8dfdf9632d4805e97d47
ARG PYTHON_IMAGE=docker.io/library/python:3.15-alpine@sha256:0f9552bb28711333da16915ec146f5e6bb44a7fdac9ced15dc17c2e0206346dd

# Copy application source only; upstream's Debian runtime is not inherited.
# hadolint ignore=DL3006
FROM ${EPISEERR_IMAGE} AS upstream

# hadolint ignore=DL3006
FROM ${PYTHON_IMAGE} AS patched

WORKDIR /app
COPY --from=upstream /app/ /app/
COPY patch-season-progress.py test-season-progress.py requirements.lock /tmp/


# hadolint ignore=DL3018
RUN apk add --no-cache tzdata \
    && python -m pip install --no-cache-dir -r /tmp/requirements.lock \
    && python /tmp/patch-season-progress.py \
    && python /tmp/test-season-progress.py \
    && python -m pip uninstall --yes pip setuptools \
    && rm /tmp/patch-season-progress.py /tmp/test-season-progress.py \
    && mkdir -p /app/logs /app/config /app/data /app/temp \
    && chown -R 1000:1000 /app

FROM scratch
COPY --from=patched / /

ENV PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
USER 1000:1000
EXPOSE 5002
CMD ["gunicorn", "--no-control-socket", "--workers", "1", "--worker-class", "gthread", "--threads", "8", "--max-requests", "2000", "--max-requests-jitter", "200", "--bind", "0.0.0.0:5002", "--access-logfile", "-", "--error-logfile", "-", "episeerr:app"]
