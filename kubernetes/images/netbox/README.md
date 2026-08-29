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
- `static/netbox_topology_views/css/vendor.css`
- `static/netbox_topology_views/js/app.js`

The `NetBox App Image` workflow builds ARM64 images after changes below this
directory and publishes the commit-SHA tag family consumed by the NetBox app.
