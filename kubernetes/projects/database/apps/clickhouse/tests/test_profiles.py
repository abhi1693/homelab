"""Keep shared admission large enough for deployment fanout and memory bounded."""

from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

import yaml

APP = Path(__file__).resolve().parents[1]
CONCURRENCY = "max_concurrent_queries_for_user"


class ClickHouseProfileTests(unittest.TestCase):
    def setUp(self):
        config = yaml.safe_load((APP / "clickhouse-config.yaml").read_text())["data"]
        self.users = ET.fromstring(config["users.xml"])
        self.server = ET.fromstring(config["resources.xml"])
        deployment = yaml.safe_load((APP / "deployment-clickhouse.yaml").read_text())
        self.template = deployment["spec"]["template"]
        self.strategy = deployment["spec"]["strategy"]
        self.container = self.template["spec"]["containers"][0]
        self.environment = {
            item["name"]: item["value"] for item in self.container["env"] if "value" in item
        }

    def value(self, element):
        if "from_env" in element.attrib:
            return self.environment[element.attrib["from_env"]]
        return (element.text or "").strip()

    def settings(self, profile):
        result = {}
        for element in self.users.find("profiles/" + profile):
            if element.tag == "profile":
                result.update(self.settings(self.value(element)))
            elif element.tag != "constraints":
                result[element.tag] = self.value(element)
        return result

    def test_service_admission_is_bounded_for_each_identity(self):
        expected = {
            "devfeed_reader": ("devfeed_reader", 8),
            "devfeed_public": ("devfeed_ingest", 8),
            "devfeed_user": ("devfeed_user", 16),
            "devfeed_partner": ("devfeed_reader", 8),
            "devfeed_admin": ("devfeed_ingest", 8),
            "devfeed_worker": ("devfeed_worker", 64),
            "devfeed_ingest": ("devfeed_ingest", 8),
        }
        self.assertEqual({user.tag for user in self.users.find("users")}, set(expected))
        for name, (profile, cap) in expected.items():
            with self.subTest(user=name):
                self.assertEqual(self.users.findtext("users/" + name + "/profile"), profile)
                self.assertEqual(int(self.settings(profile)[CONCURRENCY]), cap)

    def test_service_profiles_inherit_first_and_keep_overrides_const(self):
        for name in ("devfeed_user", "devfeed_worker"):
            with self.subTest(profile=name):
                profile = self.users.find("profiles/" + name)
                self.assertEqual(profile[0].tag, "profile")
                self.assertEqual(self.value(profile[0]), "devfeed_ingest")
                overrides = {CONCURRENCY}
                if name == "devfeed_worker":
                    overrides.add("max_memory_usage_for_user")
                self.assertEqual(
                    {
                        element.tag for element in profile
                        if element.tag not in ("profile", "constraints")
                    },
                    overrides,
                )
                self.assertEqual(
                    {element.tag for element in profile.find("constraints")}, overrides
                )
                for setting in overrides:
                    self.assertIsNotNone(profile.find("constraints/" + setting + "/readonly"))
                    self.assertIsNone(profile.find("constraints/" + setting + "/changeable_in_readonly"))

    def test_per_query_budgets_stay_bounded_as_aggregate_memory_increases(self):
        for profile in ("devfeed_ingest", "devfeed_user", "devfeed_worker", "devfeed_reader"):
            with self.subTest(profile=profile):
                settings = self.settings(profile)
                self.assertEqual(settings["max_threads"], "2")
                self.assertEqual(settings["max_memory_usage"], "268435456")
                reader = profile == "devfeed_reader"
                self.assertEqual(settings["max_execution_time"], "60" if reader else "20")
                expected = "2147483648" if profile == "devfeed_worker" else "805306368"
                self.assertEqual(settings["max_memory_usage_for_user"], expected)

    def test_wide_log_merges_retain_the_memory_fix_with_new_container_headroom(self):
        merge_tree = self.server.find("merge_tree")
        self.assertEqual(merge_tree.findtext("vertical_merge_algorithm_min_rows_to_activate"), "0")
        for name in ("merge_max_block_size", "merge_max_block_size_bytes",
                     "min_compress_block_size", "max_compress_block_size"):
            self.assertIsNone(merge_tree.find(name))
        self.assertEqual(self.container["resources"]["requests"], {"cpu": "1", "memory": "2304Mi"})
        self.assertEqual(self.container["resources"]["limits"], {"cpu": "3", "memory": "6Gi"})
        self.assertEqual(self.template["metadata"]["annotations"]["home-lab.io/config-revision"],
                         "clickhouse-admission-headroom-v3")

    def test_shared_caps_and_gitops_recreation_boundary(self):
        expected = {
            "max_server_memory_usage": "4831838208",
            "max_concurrent_queries": "128",
            "max_concurrent_select_queries": "64",
            "max_concurrent_insert_queries": "96",
        }
        for name, value in expected.items():
            with self.subTest(setting=name):
                self.assertEqual(self.value(self.server.find(name)), value)
        self.assertEqual(self.strategy["type"], "Recreate")
        self.assertEqual(self.environment["DEVFEED_CLICKHOUSE_USER_MAX_QUERIES"], "16")
        self.assertEqual(self.environment["DEVFEED_CLICKHOUSE_WORKER_MAX_QUERIES"], "64")
        mounts = {
            mount["subPath"]: mount for mount in self.container["volumeMounts"] if "subPath" in mount
        }
        self.assertEqual(
            mounts["users.xml"]["mountPath"], "/etc/clickhouse-server/users.d/devfeed-analytics.xml"
        )

    def test_worker_admission_covers_current_replicas_and_replacement_overlap(self):
        devfeed = APP.parents[2] / "applications/apps/devfeed"
        replicas = 0
        for filename in devfeed.glob("deployment-*.yaml"):
            deployment = yaml.safe_load(filename.read_text())
            container = deployment["spec"]["template"]["spec"]["containers"][0]
            if any(item.get("secretRef", {}).get("name") == "devfeed-clickhouse-worker"
                   for item in container.get("envFrom", [])):
                replicas += deployment["spec"].get("replicas", 1)
        clients = yaml.safe_load((devfeed / "configmap-clickhouse-client.yaml").read_text())["data"]
        slots = int(clients["DEVFEED_CLICKHOUSE_MAX_CONCURRENT_QUERIES"])
        # Replacement overlap doubles the ordinary per-process two-slot fanout.
        self.assertGreater(replicas, 0)
        self.assertGreaterEqual(int(self.settings("devfeed_worker")[CONCURRENCY]),
                                replicas * slots * 2)

    def test_dashboard_thresholds_match_scheduling_request_and_container_limit(self):
        import json
        dashboard = yaml.safe_load((APP / "grafana-dashboard.yaml").read_text())
        panels = json.loads(dashboard["data"]["clickhouse.json"])["panels"]
        for title, expected in (("CPU usage", [1, 3]),
                                ("Resident memory", [2304 * 1024**2, 6 * 1024**3])):
            panel = next(panel for panel in panels if panel["title"] == title)
            steps = panel["fieldConfig"]["defaults"]["thresholds"]["steps"]
            self.assertEqual([step["value"] for step in steps[1:]], expected)


if __name__ == "__main__":
    unittest.main()
