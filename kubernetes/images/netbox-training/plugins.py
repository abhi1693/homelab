"""Use the database settings loaded from this instance's NetBox configuration."""
import sys

from netbox_branching.utilities import DynamicSchemaDict

base = sys.modules["netbox.configuration.configuration"]
DATABASES = DynamicSchemaDict(base.DATABASES)
DATABASE_ROUTERS = ["netbox_branching.database.BranchAwareRouter"]
PLUGINS = ["netbox_dns", "netbox_branching"]
PLUGINS_CONFIG = {"netbox_branching": {"provision_workers": 1}}
