import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

path = Path(__file__).resolve().parents[1] / "bin/ade-nats-credential"
loader = importlib.machinery.SourceFileLoader("credential_provision", str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class CredentialTests(unittest.TestCase):
    def test_atomic_mode_idempotence_and_refused_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "credential/ade-nats-auth.json"
            value = {"authorization": {"token": "public-test-fixture-" + "a" * 32}}
            self.assertTrue(module.install_credential(target, value))
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o400)
            self.assertEqual(json.loads(target.read_text()), value)
            self.assertFalse(module.install_credential(target, value))
            with self.assertRaises(ValueError):
                module.install_credential(
                    target, {"authorization": {"token": "b" * 48}}
                )
            self.assertEqual(json.loads(target.read_text()), value)

    def test_symlink_and_policy_override_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original"
            original.write_text("unchanged")
            target = Path(directory) / "ade-nats-auth.json"
            target.symlink_to(original)
            value = {"authorization": {"token": "x" * 48}}
            with self.assertRaises(ValueError):
                module.install_credential(target, value)
            self.assertEqual(original.read_text(), "unchanged")
            with self.assertRaises(ValueError):
                module.install_credential(
                    Path(directory) / "other", {**value, "host": "0.0.0.0"}
                )


if __name__ == "__main__":
    unittest.main()
