---
title: Runbooks
---

# Runbooks

Runbooks document repeatable operator procedures for known symptoms, alerts, or
high-risk maintenance tasks.

## Standard Format

Use this structure for new runbooks:

- `Meaning`: what the symptom means and the affected system boundary.
- `Impact`: user-visible or operator-visible consequences.
- `Diagnosis`: read-only checks that confirm or rule out the issue.
- `Mitigation`: the smallest corrective action and any persistent fix.
- `Verification`: checks that prove the issue is resolved.
- `Rollback`: how to undo the mitigation if it causes a regression.
- `References`: upstream docs, related repo docs, or issue links.

Keep the first four sections present for every runbook. Add the remaining
sections when they help the operator apply or undo a local change safely.
