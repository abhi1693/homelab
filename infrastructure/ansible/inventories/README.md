# Ansible Inventories

This directory contains Ansible inventory data for bootstrap environments.

## What Belongs Here

An inventory should define:

- K3s server and agent hosts;
- host-specific connection settings;
- role variables for K3s, Cilium, kube-vip, Longhorn, Rancher, Fleet, and
  related bootstrap components;
- encrypted SOPS variables for credentials and sensitive values;
- local network assumptions such as API VIPs, node addresses, and service
  exposure ranges.

## Public Reference Use

The concrete home inventory is environment-specific. Public consumers should
create their own inventory rather than reusing hostnames, IP addresses, tokens,
or router assumptions from another lab.

Keep plaintext secrets out of inventory files. Use SOPS-encrypted variable
files for tokens, passwords, API keys, and credentials.
