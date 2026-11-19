# syntax=docker/dockerfile:1.29
FROM python:3.15-alpine@sha256:0f9552bb28711333da16915ec146f5e6bb44a7fdac9ced15dc17c2e0206346dd
RUN apk upgrade --no-cache && apk add --no-cache postgresql17-client \
    && rm -rf /usr/local/lib/python3.15/site-packages/pip* /usr/local/lib/python3.15/site-packages/setuptools*
WORKDIR /app
COPY migrate.py prepare.py schema-10.11.8.sql source-schema-10.11.8.json ./
USER 1000:1000
ENTRYPOINT ["python", "/app/prepare.py"]
