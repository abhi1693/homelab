---
title: Fleet GitJob Webhook
---

# Fleet GitJob Webhook

This bundle exposes the Fleet `gitjob` webhook receiver through the Cloudflare
Tunnel ingress at `https://fleet.abhimanyu-saharan.com/`.

The endpoint is shared by Fleet `GitRepo` resources. For multiple `GitRepo`
objects tracking the same GitHub repository, configure one repository webhook
pointing to this endpoint. For additional source repositories, add a webhook in
each repository with the same payload URL.

The runtime Secret `gitjob-webhook` in `cattle-fleet-system` stores the GitHub
webhook secret under the `github` key. It is managed by
`fleet-gitjob-webhook-secrets` through SOPS.
