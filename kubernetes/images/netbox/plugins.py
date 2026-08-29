PLUGINS = [
    "netbox_metatype_importer",
    "netbox_custom_objects",
    "netbox_topology_views",
    "netbox_dns",
    "netbox_lifecycle",
]

PLUGINS_CONFIG = {
    "netbox_metatype_importer": {
        "branch": "master",
        "github_token": "",
        "repo": "devicetype-library",
        "repo_owner": "netbox-community",
    },
}
