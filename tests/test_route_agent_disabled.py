"""route_agent honours aiuse's [disabled_services] (2026-10-12)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import route_agent as r


class OperatorDisabledTests(unittest.TestCase):
    def test_a_service_sharing_a_disabled_pool_is_disabled_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text('[disabled_services]\n"cursor" = "grokbot"\n')
            self.assertIn("cursor-cloud", r.operator_disabled(cfg))
            quota = {k: {"remaining": 0.0} for k in r.BY_NAME}
            quota["cursor-cloud"] = {"remaining": 90.0}
            c = r.route("bulk", quota=quota, exclude=r.operator_disabled(cfg))
            self.assertTrue(c is None or c.service.name != "cursor-cloud")

    def test_reads_disabled_services_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text('[disabled_services]\n"copilot" = "off"\n"cursor" = "grokbot"\n')
            self.assertEqual(r.operator_disabled(cfg), {"copilot", "cursor", "cursor-cloud"})

    def test_missing_or_bad_config_disables_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(r.operator_disabled(Path(tmp) / "absent.toml"), set())
            bad = Path(tmp) / "bad.toml"
            bad.write_text("[disabled_services\n")
            self.assertEqual(r.operator_disabled(bad), set())


if __name__ == "__main__":
    unittest.main()
