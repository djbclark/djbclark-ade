"""acp-run's git identity guard (2026-10-18): a skillopt-night replay set a fork's .git/config to
the upstream maintainer's identity and committed under it. The guard is a config-based
reference-transaction hook acp-run injects through GIT_CONFIG_COUNT."""
import ast
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools/acp-run/acp-run"
OPERATOR = "operator@example.org"
FOREIGN = "upstream@example.org"


def load_guard(guard_path: Path):
    tree = ast.parse(SCRIPT.read_text())
    keep = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "git_identity_guard":
            keep.append(n)
        elif isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "GIT_IDENTITY_GUARD_SH" for t in n.targets):
            keep.append(n)
    tree.body = keep
    ns = {"os": os, "subprocess": subprocess, "Path": Path, "GIT_IDENTITY_GUARD": guard_path}
    exec(compile(tree, str(SCRIPT), "exec"), ns)  # noqa: S102 - only repository code
    return ns["git_identity_guard"]


class TestGitIdentityGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="acp-git-id-"))
        gc = self.tmp / "gitconfig"
        gc.write_text(f"[user]\n\tname = Operator\n\temail = {OPERATOR}\n[init]\n\tdefaultBranch = main\n")
        base = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "ACP_RUN_GIT"))}
        base["GIT_CONFIG_GLOBAL"] = str(gc)
        base["GIT_CONFIG_NOSYSTEM"] = "1"
        guard = load_guard(self.tmp / "guard.sh")
        os_env = dict(os.environ)
        os.environ.clear()
        os.environ.update(base)              # git_identity_guard reads the global identity itself
        try:
            self.env = dict(base)
            guard(self.env)
        finally:
            os.environ.clear()
            os.environ.update(os_env)
        # A repo outside the temp roots the guard exempts.
        self.real = Path.home() / ".cache" / "acp-run-tests" / uuid.uuid4().hex
        self.real.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.real, True)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def git(self, repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              env=env or self.env, check=False)

    def init(self, repo: Path) -> None:
        self.assertEqual(self.git(repo, "init", "-q").returncode, 0)
        self.assertEqual(self.git(repo, "commit", "-q", "--allow-empty", "-m", "base").returncode, 0)

    def foreign(self, repo: Path) -> None:
        self.git(repo, "config", "user.name", "Upstream Maintainer")
        self.git(repo, "config", "user.email", FOREIGN)

    def head(self, repo: Path) -> str:
        return self.git(repo, "rev-parse", "HEAD").stdout.strip()

    def test_injected_config(self):
        self.assertEqual(self.env["ACP_RUN_GIT_EMAIL"], OPERATOR)
        self.assertEqual(self.env["GIT_CONFIG_COUNT"], "2")
        self.assertEqual(self.env["GIT_CONFIG_VALUE_0"], "reference-transaction")

    def test_foreign_local_identity_is_refused_even_with_no_verify(self):
        self.init(self.real)
        before = self.head(self.real)
        self.foreign(self.real)
        for extra in ([], ["--no-verify"]):
            r = self.git(self.real, "commit", "--allow-empty", "-m", "x", *extra)
            self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("identity guard", r.stderr)
            self.assertEqual(self.head(self.real), before)

    def test_operator_commit_and_foreign_author_pass(self):
        self.init(self.real)
        self.assertEqual(self.git(self.real, "commit", "-q", "--allow-empty", "-m", "ok").returncode, 0)
        r = self.git(self.real, "commit", "-q", "--allow-empty", "-m", "patch",
                     "--author", f"Upstream Maintainer <{FOREIGN}>")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_temp_repo_fixture_identity_passes(self):
        repo = self.tmp / "fixture"
        repo.mkdir()
        self.init(repo)
        self.foreign(repo)
        r = self.git(repo, "commit", "-q", "--allow-empty", "-m", "fixture")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_old_foreign_commit_fast_forward_passes(self):
        self.init(self.real)
        old = {**self.env, "GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z",
               "GIT_COMMITTER_EMAIL": FOREIGN, "GIT_AUTHOR_EMAIL": FOREIGN}
        tree = self.git(self.real, "rev-parse", "HEAD^{tree}").stdout.strip()
        sha = subprocess.run(["git", "-C", str(self.real), "commit-tree", tree, "-p", "HEAD", "-m", "up"],
                             capture_output=True, text=True, env=old, check=True).stdout.strip()
        r = self.git(self.real, "merge", "-q", "--ff-only", sha)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_repo_hooks_still_run(self):
        self.init(self.real)
        hook = self.real / ".git/hooks/pre-commit"
        hook.write_text(f"#!/bin/sh\ntouch '{self.real}/hook-ran'\n")
        hook.chmod(0o755)
        r = self.git(self.real, "commit", "-q", "--allow-empty", "-m", "ok")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.real / "hook-ran").exists())

    def test_override(self):
        self.init(self.real)
        self.foreign(self.real)
        r = self.git(self.real, "commit", "-q", "--allow-empty", "-m", "x",
                     env={**self.env, "ACP_RUN_ALLOW_GIT_IDENTITY": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
