"""route_agent honours aiuse's [disabled_services] (2026-10-12)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import route_agent as r


class OperatorDisabledTests(unittest.TestCase):
    def test_reads_disabled_services_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text('[disabled_services]\n"copilot" = "off"\n"cursor" = "grokbot"\n')
            self.assertEqual(r.operator_disabled(cfg), {"copilot", "cursor"})

    def test_missing_or_bad_config_disables_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(r.operator_disabled(Path(tmp) / "absent.toml"), set())
            bad = Path(tmp) / "bad.toml"
            bad.write_text("[disabled_services\n")
            self.assertEqual(r.operator_disabled(bad), set())


if __name__ == "__main__":
    unittest.main()
