# syntax=docker/dockerfile:1.7

ARG EPISEERR_IMAGE=docker.io/vansmak/episeerr:3.8.9@sha256:7b14478931249cc3ae3a14f7cc56354f6191dfc498a1079b0b8878c604267be7

# hadolint ignore=DL3006
FROM ${EPISEERR_IMAGE} AS patched

USER root

COPY patch-season-progress.py test-season-progress.py /tmp/

RUN python -m pip install --no-cache-dir --upgrade \
      msgpack==1.2.1 \
      setuptools==84.0.0 \
    && python /tmp/patch-season-progress.py \
    && python /tmp/test-season-progress.py \
    && python -m pip uninstall --yes pip setuptools \
    && rm /tmp/patch-season-progress.py /tmp/test-season-progress.py

USER 1000:1000

FROM scratch

COPY --from=patched / /

ENV PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

USER 1000:1000

EXPOSE 5002

CMD ["gunicorn", "--workers", "1", "--worker-class", "gthread", "--threads", "8", "--bind", "0.0.0.0:5002", "--access-logfile", "-", "--error-logfile", "-", "episeerr:app"]
