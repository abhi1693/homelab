---
title: NAS Rebuild Maintenance
---

# NAS Rebuild Maintenance

## Meaning

Use this maintenance state before rebuilding `nas.home`. It prevents
Kubernetes workloads from reading or writing the NAS media library export
through the `media/media-library-nfs-csi` PVC.

## Impact

Jellyfin, Sonarr, Radarr, Ryokan, and Shoko remain at zero replicas.
Download-only services that use the NAS-backed `media-downloads-nfs-csi` PVC can
remain running, but completed-library imports and playback are unavailable.

## Diagnosis

Confirm that no running Pod mounts the NAS-backed claim:

```bash
kubectl get pods -A -o json | jq -r '
  .items[]
  | select(.status.phase == "Running")
  | select(any(.spec.volumes[]?;
      .persistentVolumeClaim.claimName == "media-library-nfs-csi"))
  | [.metadata.namespace, .metadata.name, .spec.nodeName]
  | @tsv
'
```

The command must produce no output before NAS maintenance starts.

## Mitigation

The maintenance manifests set every active NAS consumer to zero replicas and
pause the related Fleet source and rendered workload bundles. This prevents
Fleet drift correction from restoring the workloads while the NAS is offline.

The affected source bundles are:

- `jellyfin-helmop` and rendered bundle `jellyfin`;
- `radarr-helmop` and rendered bundle `radarr`;
- `sonarr-helmop` and rendered bundle `sonarr`;
- `media-ryokan`;
- `media-shoko`.

## Verification

Confirm the workload state:

```bash
kubectl -n media get deployment \
  jellyfin radarr sonarr ryokan shoko \
  -o custom-columns='NAME:.metadata.name,DESIRED:.spec.replicas,AVAILABLE:.status.availableReplicas'
```

Every Deployment must show `0` desired replicas. Repeat the no-running-Pod query
from `Diagnosis` after Fleet has completed a reconciliation interval.

## Recovery

After the rebuilt NAS is online and `192.168.3.115:/nfs/media_new` is mounted
and verified, restore the media workloads:

- remove `paused: true` from the five affected `fleet.yaml` files and the three
  `HelmOp` specs;
- restore Jellyfin, Sonarr, Radarr, Ryokan, and Shoko to one replica;
- remove the maintenance notices from the affected README files.

Commit and push the recovery change, then let Fleet reconcile. Verify that the
PVC mounts successfully and workloads become Ready before starting any new
imports. Do not use `kubectl scale` as the normal recovery path because Fleet
drift correction will overwrite it.

## References

- `kubernetes/projects/entertainment/README.md`
- `kubernetes/projects/entertainment/apps/media-storage/README.md`
- `kubernetes/projects/entertainment/apps/media-storage/nas-library-pv.yaml`
