# syntax=docker/dockerfile:1.28

ARG EPISEERR_IMAGE=docker.io/vansmak/episeerr:3.9.8@sha256:9766c7f657035e606ac8a2f43f24de23b97ba73f12c2610482b486f762214f4d
ARG PYTHON_IMAGE=docker.io/library/python:3.15-alpine@sha256:ff4d3c9b1a48f646eedd93182aaea385c7a5452f4c8a8cd7cef686babacf4928

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
CMD ["gunicorn", "--workers", "1", "--worker-class", "gthread", "--threads", "8", "--bind", "0.0.0.0:5002", "--access-logfile", "-", "--error-logfile", "-", "episeerr:app"]
