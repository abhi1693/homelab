# Infrastructure Patches

This directory is reserved for infrastructure-level patches that do not belong
inside an application image directory.

Use this area when a patch applies to bootstrap tooling, host-level behavior, or
an infrastructure dependency that is not better represented as:

- an Ansible role template;
- a Kubernetes manifest;
- a Docker image patch under `kubernetes/images/<image>/patches/`;
- a runbook under `docs/runbooks/`.

At the moment, app image patches live near their images under
`kubernetes/images/`, which keeps the Dockerfile, patch, and README together.
