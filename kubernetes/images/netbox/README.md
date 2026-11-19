# NetBox Image

This image extends the pinned upstream NetBox image with the plugins in
`required-plugins.txt`. The same plugin list is declared in `plugins.py` only
for the image build so Django can discover and collect plugin static assets.
The Helm chart renders the authoritative runtime plugin configuration.

Run `collectstatic` after installing plugins. Plugins such as
`netbox-topology-views` ship JavaScript, CSS, and image files outside the base
image's pre-collected static root. Installing the Python package without
collecting those files leaves the topology page available while its browser
assets return `404`.

The Dockerfile verifies these required topology assets before publishing:

- `static/netbox_topology_views/css/app.css`
- `static/netbox_topology_views/js/app.js`

The build also compares every installed plugin version with its exact pin in
`required-plugins.txt`, using `verify_plugins.py`. That file is the source of
truth for installation and verification; dependency updates do not require a
second version list in the Dockerfile. Missing plugins, different installed
versions and requirements without exact pins fail the build. Run the focused
regression checks with `python3 -m unittest discover -s kubernetes/images/netbox/tests -v`.

The `NetBox App Image` workflow builds ARM64 images after changes below this
directory and publishes the commit-SHA tag family consumed by the NetBox app.

## NetBox 4.7 image qualification

The native ARM64 build pins the official NetBox 4.7.4 base by OCI digest and
retains its installed package versions while adding compatible plugin versions:
custom objects 0.7.2, topology views 4.7.0, DNS 1.7.3 and lifecycle 1.1.11.
The metatype importer is omitted because upstream still declares a 4.6.99
maximum. The running application's plugin list is changed only at cutover;
plugin tables and retained credentials are not deleted.

The workflow requires strict HIGH/CRITICAL and secret scanning with unfixed
findings included, plus an SBOM and provenance, before publishing an immutable
`4.7.4-<commit>` image. Native collectstatic initializes Django and checks plugin
compatibility and topology assets. Fleet image pins are updated separately
after database migration qualification and rollback preparation.

These source plugin pins do not change the separately pinned running image.
Lifecycle 1.1.11 adds owner foreign-key changes, and custom objects 0.7.2 adds
decimal and multi-select column widening. Qualify those migrations against a
restored database before selecting a new runtime image; the widening can
rewrite custom-object tables and its reverse migration does not narrow them.
