"""Identity guards for the one-time planner-statistics maintenance Job."""

import ast
import math
from pathlib import Path
import unittest

import yaml

APP = Path(__file__).resolve().parents[1]
JOB = yaml.safe_load((APP / "report-day-statistics-job.yaml").read_text())
PROGRAM = JOB["spec"]["template"]["spec"]["containers"][0]["command"][2]
TREE = ast.parse(PROGRAM)
NODES = [
    node
    for node in TREE.body
    if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    and node.name in {"MaintenanceError", "require", "validate_identity", "day_bound"}
]
SCOPE = {"math": math, "EXPRESSION": "date(timezone('UTC'::text, finished_at))"}
exec(compile(ast.Module(body=NODES, type_ignores=[]), "inline-statistics-guards", "exec"), SCOPE)


class StatisticsIdentity(unittest.TestCase):
    def setUp(self):
        self.existing = {
            "relation": 100,
            "owner": 200,
            "keys": "",
            "kinds": ["e"],
            "expression": SCOPE["EXPRESSION"],
        }

    def test_existing_correct_identity_can_be_reused(self):
        SCOPE["validate_identity"](self.existing, 100, 200)

    def test_same_name_does_not_trust_wrong_metadata(self):
        for key, value, check in (
            ("relation", 101, "statistics.relation"),
            ("owner", 201, "statistics.owner"),
            ("keys", "1", "statistics.columns"),
            ("kinds", ["d", "e"], "statistics.kind"),
            ("expression", "date(timezone('UTC'::text, created_at))", "statistics.expression"),
        ):
            with self.subTest(key=key):
                row = {**self.existing, key: value}
                with self.assertRaisesRegex(SCOPE["MaintenanceError"], "^" + check + "$"):
                    SCOPE["validate_identity"](row, 100, 200)

    def test_full_table_day_bound_handles_postgresql_fractional_statistics(self):
        self.assertEqual(SCOPE["day_bound"](40, 2500), 40)
        self.assertEqual(SCOPE["day_bound"](-0.2, 200), 40)
        self.assertEqual(SCOPE["day_bound"](-1, 200), 200)
        for count, rows in ((None, 200), (0, 200), (-2, 200), (4000, 5000), (0, 0)):
            with self.subTest(count=count, rows=rows):
                with self.assertRaises(SCOPE["MaintenanceError"]):
                    SCOPE["day_bound"](count, rows)

    def test_regular_job_has_bounded_runtime_and_no_extra_database_access(self):
        self.assertNotIn("helm.sh/hook", JOB["metadata"].get("annotations", {}))
        self.assertEqual(JOB["spec"]["backoffLimit"], 0)
        self.assertEqual(JOB["spec"]["activeDeadlineSeconds"], 300)
        pod = JOB["spec"]["template"]["spec"]
        self.assertEqual(pod["restartPolicy"], "Never")
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["nodeSelector"], {"kubernetes.io/arch": "arm64"})
        container = pod["containers"][0]
        self.assertEqual(container["securityContext"]["runAsUser"], 10001)
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(container["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertEqual(
            [item["secretRef"]["name"] for item in container["envFrom"] if "secretRef" in item],
            ["devfeed-read-model-database"],
        )
        env = {item["name"]: item for item in container["env"]}
        self.assertEqual(
            env["DEVFEED_DATABASE_URL"]["valueFrom"]["secretKeyRef"],
            {"name": "devfeed-read-model-database", "key": "DEVFEED_READ_MODEL_DATABASE_URL"},
        )
        self.assertNotIn("devfeed-database-client", JOB["spec"]["template"]["metadata"]["labels"])


if __name__ == "__main__":
    unittest.main()
