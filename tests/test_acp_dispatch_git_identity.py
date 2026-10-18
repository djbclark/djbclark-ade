"""acp-dispatch warns when a slice's repo config names someone other than the operator (2026-10-18)."""
import importlib.machinery
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def load():
    loader = importlib.machinery.SourceFileLoader(
        "acp_dispatch_identity", str(Path(__file__).resolve().parent.parent / "bin" / "acp-dispatch"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestGitIdentityWarning(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="acpd-gid-"))
        gc = self.tmp / "gitconfig"
        gc.write_text("[user]\n\tname = Operator\n\temail = operator@example.org\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL=str(gc), GIT_CONFIG_NOSYSTEM="1")
        self.patch = mock.patch.dict(os.environ, env, clear=True)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.repo = self.tmp / "repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.mod = load()

    def test_operator_identity_is_quiet(self):
        self.assertIsNone(self.mod.git_identity_warning(self.repo))

    def test_local_foreign_identity_warns(self):
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Upstream"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "up@example.org"], check=True)
        msg = self.mod.git_identity_warning(self.repo)
        self.assertIn("Upstream <up@example.org>", msg)
        self.assertIn("local config", msg)
        self.assertIn("--local --unset user.name", msg)

    def test_not_a_repo_is_quiet(self):
        self.assertIsNone(self.mod.git_identity_warning(self.tmp / "nowhere"))


if __name__ == "__main__":
    unittest.main()
