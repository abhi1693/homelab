# Rancher Compliance Scans

Fleet-managed Compliance scan definitions for the home lab.

- `home-lab-k3s-cis-initial` runs once after Rancher Compliance is installed, so
  the first report can be reviewed for hardening work.
- `home-lab-k3s-cis-monthly` runs the built-in `k3s-cis-1.12-profile` at
  `03:00` on the first day of every month and retains the last 12 scheduled
  runs.
