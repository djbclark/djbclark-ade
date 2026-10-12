"""The overload gate in bin/acp-dispatch: holds, caps, records, and can be skipped."""
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_loader = importlib.machinery.SourceFileLoader("acp_dispatch_gate", str(ROOT / "bin" / "acp-dispatch"))
_spec = importlib.util.spec_from_loader("acp_dispatch_gate", _loader)
acpd = importlib.util.module_from_spec(_spec)
_loader.exec_module(acpd)


class GateTest(unittest.TestCase):
    def setUp(self):
        self.rec = Path(tempfile.mkdtemp()) / "rec.json"
        self.rec.write_text(json.dumps({"x": 1}))

    def gate(self) -> str | None:
        return json.loads(self.rec.read_text()).get("gate")

    def test_idle_machine_starts_at_once(self):
        with mock.patch.dict(os.environ, {"ACP_DISPATCH_NO_GATE": "0"}), \
             mock.patch.object(acpd, "machine_overloaded", return_value=None):
            acpd.wait_for_capacity(self.rec)
        self.assertIsNone(self.gate())

    def test_holds_until_load_drops(self):
        seq = iter(["load 99 > 4x8 cpus", "load 99 > 4x8 cpus", None])
        with mock.patch.dict(os.environ, {"ACP_DISPATCH_NO_GATE": "0"}), \
             mock.patch.object(acpd, "machine_overloaded", side_effect=lambda: next(seq)), \
             mock.patch.object(acpd, "GATE_POLL_S", 0):
            acpd.wait_for_capacity(self.rec)
        self.assertRegex(self.gate(), r"^waited \d+s$")

    def test_cap_starts_anyway(self):
        with mock.patch.dict(os.environ, {"ACP_DISPATCH_NO_GATE": "0", "ACP_DISPATCH_GATE_MAX": "0"}), \
             mock.patch.object(acpd, "machine_overloaded", return_value="memory pressure critical"):
            acpd.wait_for_capacity(self.rec)
        self.assertIn("started anyway: memory pressure critical", self.gate())

    def test_no_gate_skips(self):
        with mock.patch.dict(os.environ, {"ACP_DISPATCH_NO_GATE": "1"}), \
             mock.patch.object(acpd, "machine_overloaded", return_value="load 99 > 4x8 cpus") as m:
            acpd.wait_for_capacity(self.rec)
        m.assert_not_called()
        self.assertIsNone(self.gate())


if __name__ == "__main__":
    unittest.main()
