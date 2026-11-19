"""Local relationship evidence cannot become permission to contact an agent."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import ade_coord as coord


def enrollment():
    return {
        "roles": {"lead": {"controller": True, "controlled_pilot": True,
                           "runtime": {"owner": {"host": "h", "server": "s", "agent": "lead-new"}}}},
        "aliases": {"lead-new": "lead", "lead-old": "lead", "lead-next": "lead"},
        "assignments": {"worker": {"recipient_role": "lead"}},
    }


class RelationshipTests(unittest.TestCase):
    def query(self, agent, cfg):
        with patch.object(coord, "call", side_effect=AssertionError("broker call")):
            result = coord.agent_relationships({"agent_id": agent}, cfg=cfg)
        self.assertFalse(result["contact_authority"])
        self.assertFalse(result["current_owner_verified"])
        self.assertTrue(result["requires_online_owner_revalidation"])
        self.assertFalse(result["workers_complete"])
        return result

    def test_explicit_worker_and_configured_owner_edges_without_mutation(self):
        cfg = enrollment(); before = copy.deepcopy(cfg)
        worker = self.query("worker", cfg)
        self.assertEqual(worker["controller"]["status"], "known")
        self.assertEqual(worker["controller"]["configured_owner"]["agent"], "lead-new")
        lead = self.query("lead-new", cfg)
        self.assertEqual(lead["configured_owned_roles"], ["lead"])
        self.assertEqual([item["agent_id"] for item in lead["workers"]], ["worker"])
        self.assertEqual(lead["controller"]["status"], "unknown")
        self.assertEqual(cfg, before)

    def test_absence_aliases_and_controller_flags_do_not_imply_a_root_lead(self):
        cfg = enrollment()
        for agent in ["unknown", "lead-old", "lead-next"]:
            with self.subTest(agent=agent):
                result = self.query(agent, cfg)
                self.assertEqual(result["controller"]["status"], "unknown")
                self.assertEqual(result["configured_owned_roles"], [])
                self.assertEqual(result["workers"], [])
        del cfg["roles"]["lead"]["runtime"]
        self.assertEqual(self.query("worker", cfg)["controller"]["status"], "unknown")

    def test_missing_malformed_and_inconsistent_owner_evidence_stays_unknown(self):
        cases = [None, {}, {"recipient_role": []}, {"recipient_role": "absent"}]
        for assignment in cases:
            cfg = enrollment(); cfg["assignments"]["worker"] = assignment
            with self.subTest(assignment=assignment):
                self.assertEqual(self.query("worker", cfg)["controller"]["status"], "unknown")
        for owner in [None, {}, {"agent": "lead-new"}, {"agent": [], "host": "h", "server": "s"}]:
            cfg = enrollment(); cfg["roles"]["lead"]["runtime"]["owner"] = owner
            with self.subTest(owner=owner):
                self.assertEqual(self.query("worker", cfg)["controller"]["status"], "unknown")
        cfg = enrollment(); cfg["aliases"]["lead-new"] = "absent"
        self.assertEqual(self.query("worker", cfg)["controller"]["status"], "unknown")

    def test_self_and_multi_agent_cycles_are_ambiguous_in_both_directions(self):
        cfg = enrollment(); cfg["assignments"]["lead-new"] = {"recipient_role": "lead"}
        self.assertEqual(self.query("worker", cfg)["controller"]["status"], "ambiguous")
        self.assertEqual(self.query("lead-new", cfg)["controller"]["status"], "ambiguous")
        cfg["roles"]["other"] = {"runtime": {"owner": {"host": "h", "server": "s", "agent": "worker"}}}
        cfg["aliases"]["worker"] = "other"
        cfg["assignments"]["lead-new"] = {"recipient_role": "other"}
        result = self.query("worker", cfg)
        self.assertEqual(result["controller"]["status"], "ambiguous")
        self.assertEqual(result["workers"][0]["status"], "ambiguous")

    def test_invalid_query_and_unenrolled_query_fail_closed(self):
        for agent in [None, "", " ", [], 1]:
            with self.subTest(agent=agent), self.assertRaisesRegex(coord.CoordinationError, "AGENT_ID_REQUIRED"):
                coord.agent_relationships({"agent_id": agent}, cfg=enrollment())
        with patch.object(coord, "config", return_value=None):
            result = coord.agent_relationships({"agent_id": "unknown"})
        self.assertEqual(result["controller"]["status"], "unknown")
        self.assertFalse(result["contact_authority"])

    def test_json_driver_is_isolated_read_only_and_never_uses_broker_or_native_parent(self):
        driver = Path(__file__).resolve().parents[1] / "bin/ade-coord"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); config_path = root / "config.json"; manifest = root / "generation.json"
            manifest.write_text(json.dumps({"generation": "g", "reconciled": True}))
            cfg = {**enrollment(), "generation": "g", "generation_manifest": str(manifest),
                   "state_dir": str(root / "state"), "identity": {"host": "h", "server": "s"},
                   "claims": {}, "credential_boundary": "/must-not-run", "broker_url": "must-not-contact"}
            config_path.write_text(json.dumps(cfg))
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            env = {**os.environ, "ADE_COORD_CONFIG": str(config_path), "ADE_COORD_NODE": "/must-not-run",
                   "ADE_COORD_METRICS": str(root / "must-not-write"), "PASEO_AGENT_ID": "wrong-native-parent"}
            result = subprocess.run([sys.executable, "-I", str(driver), "agent", "relationships"],
                                    input='{"agent_id":"worker"}', capture_output=True, text=True, env=env, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data["ok"])
            self.assertEqual(data["result"]["controller"]["configured_owner"]["agent"], "lead-new")
            self.assertFalse(data["result"]["contact_authority"])
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)


if __name__ == "__main__":
    unittest.main()
