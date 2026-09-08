"""Failure-path tests for the rolling control-plane barrier (no cluster access)."""

import copy
import datetime as dt
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "files/check_server_health.py"
SPEC = importlib.util.spec_from_file_location("server_health", SOURCE)
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)


class EtcdTests(unittest.TestCase):
    def setUp(self):
        self.nodes = ["node-1", "node-2", "node-3"]
        self.servers = ["192.0.2.1", "192.0.2.2", "192.0.2.3"]
        self.ids = [6000446796562384172, 251898858488160300, 5323064694785386254]
        self.members = [{"ID": mid, "name": node + "-abc123",
                         "peerURLs": [f"https://{ip}:2380"],
                         "clientURLs": [f"https://{ip}:2379"]}
                        for mid, node, ip in zip(self.ids, self.nodes, self.servers)]
        self.statuses = [{"header": {"cluster_id": 42, "member_id": mid}, "raftTerm": 12,
                          "leader": self.ids[0], "raftIndex": 100, "raftAppliedIndex": 99}
                         for mid in self.ids]
        self.memberships = [{"header": {"cluster_id": 42}, "members": copy.deepcopy(self.members)}
                            for _ in self.ids]

    def validate(self, baseline=None):
        return health.validate_etcd(self.statuses, self.memberships, self.nodes,
                                    self.servers, 10, baseline or [])

    def test_healthy_members_and_large_ids_are_preserved(self):
        members, consensus = self.validate()
        self.assertEqual(consensus, ("42", str(self.ids[0]), 12))
        self.assertEqual({m[0] for m in members}, {str(i) for i in self.ids})

    def test_missing_endpoint_blocks(self):
        self.statuses.pop()
        with self.assertRaises(health.Unhealthy):
            self.validate()

    def test_cluster_term_and_leader_disagreement_block(self):
        for field in ("raftTerm", "leader"):
            with self.subTest(field=field):
                original = self.statuses[1][field]
                self.statuses[1][field] = 123
                with self.assertRaises(health.Unhealthy):
                    self.validate()
                self.statuses[1][field] = original
        self.statuses[2]["header"]["cluster_id"] = 456
        with self.assertRaises(health.Unhealthy):
            self.validate()

    def test_learner_or_peer_drift_blocks(self):
        self.memberships[0]["members"][1]["isLearner"] = True
        with self.assertRaises(health.Unhealthy):
            self.validate()
        self.memberships[0]["members"][1]["isLearner"] = False
        self.memberships[0]["members"][1]["peerURLs"] = ["https://192.0.2.99:2380"]
        with self.assertRaises(health.Unhealthy):
            self.validate()

    def test_membership_disagreement_and_replacement_block(self):
        baseline, _ = self.validate()
        self.memberships[2]["members"][0]["name"] = "node-1-replaced"
        with self.assertRaises(health.Unhealthy):
            self.validate()
        for membership in self.memberships:
            membership["members"][0]["name"] = "node-1-replaced"
        with self.assertRaises(health.Unhealthy):
            self.validate(baseline)

    def test_index_lag_and_endpoint_errors_block(self):
        self.statuses[1]["raftAppliedIndex"] = 80
        with self.assertRaises(health.Unhealthy):
            self.validate()
        self.statuses[1]["raftAppliedIndex"] = 99
        self.statuses[1]["errors"] = ["unhealthy"]
        with self.assertRaises(health.Unhealthy):
            self.validate()


class PlatformTests(unittest.TestCase):
    def test_old_ready_deployment_does_not_hide_incomplete_rollout(self):
        deployment = {"kind": "Deployment", "metadata": {"namespace": "system", "name": "dns", "generation": 4},
                      "spec": {"replicas": 2}, "status": {"observedGeneration": 4, "readyReplicas": 2,
                                                         "availableReplicas": 2, "updatedReplicas": 1}}
        with self.assertRaises(health.Unhealthy):
            health.validate_controller(deployment)
        deployment["status"]["updatedReplicas"] = 2
        health.validate_controller(deployment)
        deployment["status"]["observedGeneration"] = 3
        with self.assertRaises(health.Unhealthy):
            health.validate_controller(deployment)

    def test_empty_daemonset_does_not_pass(self):
        daemonset = {"kind": "DaemonSet", "metadata": {"namespace": "system", "name": "cni", "generation": 1},
                     "status": {"observedGeneration": 1, "desiredNumberScheduled": 0}}
        with self.assertRaises(health.Unhealthy):
            health.validate_controller(daemonset)

    def test_stale_lease_blocks(self):
        old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=90)
        with self.assertRaises(health.Unhealthy):
            health.recent_lease({"spec": {"renewTime": old.isoformat()}})

    def test_fleet_ready_parent_does_not_hide_waitapplied(self):
        repo = {"metadata": {"name": "home-lab-test", "generation": 1}, "status": {
            "observedGeneration": 1, "desiredReadyClusters": 1, "readyClusters": 1,
            "conditions": [{"type": "Ready", "status": "True"}],
            "resourceCounts": {"desiredReady": 10, "ready": 10},
            "display": {"readyBundleDeployments": "2/2"}}}
        health.validate_gitrepo(repo)
        repo["status"]["resourceCounts"]["waitApplied"] = 1
        with self.assertRaises(health.Unhealthy):
            health.validate_gitrepo(repo)

    def test_failed_sample_resets_stability_counter(self):
        checker = health.Checker({"timeout": 60, "interval": 20, "samples": 2,
                                  "etcdctl": "/test/etcdctl", "etcdctl_version": "3.6.14"})
        clock = [0]
        checker.deadline = 200
        def advance(seconds):
            clock[0] += seconds
        with patch.object(checker, "run", return_value="etcdctl version: 3.6.14"), \
             patch.object(checker, "sample", side_effect=[("leader", []), health.Unhealthy("lost quorum"),
                                                          ("leader", []), ("leader", [])]) as sample, \
             patch.object(health.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(health.time, "sleep", side_effect=advance):
            result = checker.wait()
        self.assertEqual(sample.call_count, 4)
        self.assertEqual(result["stable_samples"], 2)

    def test_persistent_failure_is_bounded(self):
        checker = health.Checker({"timeout": 60, "interval": 20, "samples": 2,
                                  "etcdctl": "/test/etcdctl", "etcdctl_version": "3.6.14"})
        clock = [0]
        checker.deadline = 60
        def advance(seconds):
            clock[0] += seconds
        with patch.object(checker, "run", return_value="etcdctl version: 3.6.14"), \
             patch.object(checker, "sample", side_effect=health.Unhealthy("lost quorum")), \
             patch.object(health.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(health.time, "sleep", side_effect=advance):
            with self.assertRaisesRegex(health.Unhealthy, "timed out"):
                checker.wait()
        self.assertEqual(clock[0], 60)


if __name__ == "__main__":
    unittest.main()
