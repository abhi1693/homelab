# Longhorn Volume Overrides

One-time Longhorn volume policy corrections that are safer to apply through
Fleet than by taking ownership of Longhorn's dynamic `Volume` resources.

This bundle currently disables data locality on build-cache volumes whose
workloads do not need a same-node Longhorn replica. Keeping those volumes at
`best-effort` can leave Longhorn reporting local replica scheduling failures
when the attached node has too little scheduled-capacity headroom.
