# Student NetBox image

The ARM64 student image extends the deployed NetBox 4.7.4 base. It installs NetBox DNS and NetBox Branching and collects their static assets. The image configuration loads DNS first and Branching last, wraps the database connection supplied by the Helm chart, and uses one provisioning worker per branch within each student's ten-connection role limit.

Build with `docker buildx build --platform linux/arm64 -t <registry>/<repository>:<tag> --push kubernetes/images/netbox-training`. Pin the published digest in `kubernetes/projects/training/_shared/netbox/student-plugins/values.yaml`, then run `python3 scripts/render-training-netbox.py`. The image serves both web and worker deployments.
