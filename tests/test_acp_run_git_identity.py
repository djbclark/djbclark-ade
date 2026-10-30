"""acp-run's git identity guard (2026-10-18): a skillopt-night replay set a fork's .git/config to
the upstream maintainer's identity and committed under it. The guard is a config-based
reference-transaction hook acp-run injects through GIT_CONFIG_PARAMETERS."""
import ast
import asyncio
import io
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "tools/acp-run/acp-run"
OPERATOR = "operator@example.org"
FOREIGN = "upstream@example.org"


def load_guard(guard_path: Path):
    tree = ast.parse(SCRIPT.read_text())
    keep = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in {"git_identity_guard", "git_config_parameters",
                                                         "credential_url_key"}:
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
        # Keep assertion failures synthetic: never copy ambient credentials or browser capabilities.
        base = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "SHELL", "LANG", "LC_ALL") if k in os.environ}
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
        self.assertFalse("GIT_CONFIG_COUNT" in self.env)
        self.assertEqual(self.git(self.real, "config", "--get", "hook.acp-run-identity.event").stdout.strip(),
                         "reference-transaction")

    def test_installed_codex_keeps_the_guard_and_default_exclusions(self):
        from test_codex_shell_env_policy import CODEX, SYNTHETIC_SECRETS, base_env, policy_toml, rendered, tool_env

        if not CODEX:
            self.skipTest("no installed codex")
        home = str(self.tmp)
        (self.tmp / "tmp").mkdir()
        # Only synthetic configuration reaches the RPC probe, never the operator's environment.
        injected = {k: v for k, v in self.env.items() if k.startswith("GIT_CONFIG_") or k == "ACP_RUN_GIT_EMAIL"}
        got = tool_env(policy_toml(rendered(home)["shell_environment_policy"]), {**base_env(home), **injected})
        for name in SYNTHETIC_SECRETS:
            self.assertNotIn(name, got)
        self.init(self.real)
        hook = self.real / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\ntouch %s\n" % shlex.quote(str(self.real / "hook-ran")))
        hook.chmod(0o755)
        r = self.git(self.real, "commit", "-q", "--allow-empty", "-m", "operator", env=got)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.real / "hook-ran").exists())
        before = self.head(self.real)
        self.foreign(self.real)
        for extra in ([], ["--no-verify"]):
            r = self.git(self.real, "commit", "--allow-empty", "-m", "foreign", *extra, env=got)
            self.assertNotEqual(r.returncode, 0, r.stderr)
            self.assertIn("identity guard", r.stderr)
            self.assertEqual(self.head(self.real), before)

    def test_hook_path_with_an_apostrophe_still_runs(self):
        """The generated hook names its output path through shlex.quote: a home directory with an apostrophe
        must not turn the hook into a shell syntax error before the guard is even reached."""
        repo = self.real / "it's a repo"
        repo.mkdir()
        self.init(repo)
        hook = repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\ntouch %s\n" % shlex.quote(str(repo / "hook-ran")))
        hook.chmod(0o755)
        r = self.git(repo, "commit", "-q", "--allow-empty", "-m", "operator")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((repo / "hook-ran").exists())

    def test_counted_values_and_existing_parameters_keep_their_order_and_quoting(self):
        values = ["plain", "space here", "a'b", "a\\b", "line\nbreak", "a=b", "!", ""]
        env = {**self.env, "GIT_CONFIG_COUNT": str(len(values)),
               "GIT_CONFIG_PARAMETERS": "'ade.example=parameters'"}
        for i, value in enumerate(values):
            env[f"GIT_CONFIG_KEY_{i}"] = "ade.a=b.example"
            env[f"GIT_CONFIG_VALUE_{i}"] = value
        env["GIT_CONFIG_PARAMETERS"] = "'ade.a=b.example'='parameters'"
        load_guard(self.tmp / "guard.sh")(env)  # nested launch still normalizes its caller's counted entries
        self.assertNotIn("GIT_CONFIG_COUNT", env)
        r = self.git(self.real, "config", "--get-all", "ade.a=b.example", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "".join(v + "\n" for v in [*values, "parameters"]))

    def test_nested_launch_is_idempotent_and_converts_legacy_guard_pairs(self):
        guard = load_guard(self.tmp / "guard.sh")
        env = dict(self.env)
        guard(env)
        self.assertEqual(env, self.env)
        legacy = {**self.env, "GIT_CONFIG_COUNT": "2",
                  "GIT_CONFIG_KEY_0": "hook.acp-run-identity.event", "GIT_CONFIG_VALUE_0": "reference-transaction",
                  "GIT_CONFIG_KEY_1": "hook.acp-run-identity.command", "GIT_CONFIG_VALUE_1": str(self.tmp / "guard.sh")}
        legacy.pop("GIT_CONFIG_PARAMETERS", None)
        guard(legacy)
        self.assertEqual(legacy, self.env)

    def test_zero_count_formats_accepted_by_git_are_preserved(self):
        guard = load_guard(self.tmp / "guard.sh")
        for count in ("0", "+0", "-0", " 0", "00"):
            with self.subTest(count=count):
                env = {**self.env, "GIT_CONFIG_COUNT": count}
                guard(env)
                self.assertEqual(env, self.env)

    def test_fresh_guard_preserves_inherited_configuration(self):
        env = {**self.env, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "ade.example",
               "GIT_CONFIG_VALUE_0": "counted", "GIT_CONFIG_PARAMETERS": "'ade.example=parameters'"}
        env.pop("ACP_RUN_GIT_EMAIL")
        with mock.patch.dict(os.environ, self.env, clear=True):
            load_guard(self.tmp / "guard.sh")(env)
        r = self.git(self.real, "config", "--get-all", "ade.example", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "counted\nparameters\n")
        r = self.git(self.real, "config", "--get", "hook.acp-run-identity.command", env=env)
        self.assertEqual(r.stdout.strip(), str(self.tmp / "guard.sh"))
        self.assertEqual(env["ACP_RUN_GIT_EMAIL"], OPERATOR)

    def test_counted_configuration_is_normalized_even_without_an_operator_identity(self):
        env = {**self.env, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "ade.example", "GIT_CONFIG_VALUE_0": "kept"}
        env.pop("ACP_RUN_GIT_EMAIL")
        env.pop("GIT_CONFIG_PARAMETERS")
        with mock.patch("subprocess.run", return_value=SimpleNamespace(stdout="")):
            load_guard(self.tmp / "guard.sh")(env)
        self.assertNotIn("ACP_RUN_GIT_EMAIL", env)
        r = self.git(self.real, "config", "--get", "ade.example", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "kept\n")

    def test_malformed_counted_config_is_rejected_without_mutation_or_values(self):
        guard = load_guard(self.tmp / "guard.sh")
        for fields, missing in [({"GIT_CONFIG_COUNT": "not-a-number"}, "GIT_CONFIG_COUNT"),
                                ({"GIT_CONFIG_COUNT": "-1"}, "GIT_CONFIG_COUNT"),
                                ({"GIT_CONFIG_COUNT": "100000000000000000000"}, "GIT_CONFIG_COUNT"),
                                ({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_VALUE_0": "private-value"}, "GIT_CONFIG_KEY_0"),
                                ({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "ade.example"}, "GIT_CONFIG_VALUE_0")]:
            with self.subTest(missing=missing, fields=tuple(fields)):
                env = {**self.env, **fields}
                before = dict(env)
                with self.assertRaisesRegex(ValueError, missing) as raised:
                    guard(env)
                self.assertNotIn("private-value", str(raised.exception))
                self.assertEqual(env, before)

    def test_counted_key_with_an_embedded_credential_is_refused_by_index_only(self):
        guard = load_guard(self.tmp / "guard.sh")
        # git sections are case-insensitive: `URL.https://...` is the same setting, measured with
        # `git config --get` on the lowercase spelling; and an empty authority (`https:///user:tok@host`)
        # still sends that userinfo, so the run of slashes must not hide it
        for key in ("url.https://user:s3cr3t@example.org/.insteadOf",
                    "url.ssh://deploy:s3cr3t@example.org/.pushInsteadOf",
                    "URL.https://user:s3cr3t@example.org/.insteadOf",
                    "url.https:///user:s3cr3t@example.org/.insteadOf",
                    # `url.*` is not the only URL-scoped family: git resolves these for the matching
                    # URL too (`git config --get-urlmatch http.sslVerify https://user:tok@host/x`),
                    # and the exposure is the NAME, whatever the section means
                    "http.https://user:s3cr3t@example.org/.sslVerify",
                    "credential.https://user:s3cr3t@example.org.helper",
                    "HTTP.https://user:s3cr3t@example.org/.extraHeader",
                    # an upper-case scheme, and a nested URL in a path: refused as a fail-closed
                    # extra, because the token is in the name either way
                    "url.HTTPS://user:s3cr3t@example.org/.insteadOf",
                    "url.https://example.org/r?u=https://user:s3cr3t@h/.insteadOf",
                    # a PARTIAL credential url has no scheme but is a real subsection git matches
                    # (`match_partial_url`): measured with `git credential fill`, a helper under
                    # `credential.user:s3cr3t@example.org.helper` runs for
                    # `url=https://user:s3cr3t@example.org/x`. No colon is required either, because a
                    # PAT is used as a username and git url-decodes `%3A`
                    "credential.user:s3cr3t@example.org.helper",
                    "credential.alice@example.org.helper",
                    "credential.ghp_FAKE0123456789@example.org.helper",
                    "credential.user%3As3cr3t@example.org.helper",
                    "CREDENTIAL.user:s3cr3t@example.org.helper"):
            with self.subTest(key=key):
                env = {**self.env, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": key,
                       "GIT_CONFIG_VALUE_0": "https://example.org/"}
                before = dict(env)
                with self.assertRaisesRegex(ValueError, "GIT_CONFIG_KEY_0 embeds a credential") as raised:
                    guard(env)
                self.assertNotIn("s3cr3t", str(raised.exception))
                self.assertEqual(env, before)

    def test_keys_without_userinfo_still_travel(self):
        guard = load_guard(self.tmp / "guard.sh")
        # scp-like bases have no `://`, a `@` outside a URL is not userinfo, a `@` in the first path
        # segment is a path, and the other URL-scoped families travel when they carry no userinfo.
        # The last two are `credential.` subsections with no userinfo: a port must not make a real
        # config unlaunchable, and a schemeless partial url is the ordinary case git matches
        env = {**self.env, "GIT_CONFIG_COUNT": "7",
               "GIT_CONFIG_KEY_0": "url.git@example.org:.insteadOf",
               "GIT_CONFIG_VALUE_0": "https://mirror.example.org/",
               "GIT_CONFIG_KEY_1": "url.https://example.org/.insteadOf",
               "GIT_CONFIG_VALUE_1": "https://mirror2.example.org/",
               "GIT_CONFIG_KEY_2": "url.https://example.org/@scope/.insteadOf",
               "GIT_CONFIG_VALUE_2": "https://mirror3.example.org/",
               "GIT_CONFIG_KEY_3": "http.https://example.org/.sslVerify",
               "GIT_CONFIG_VALUE_3": "true",
               "GIT_CONFIG_KEY_4": "credential.https://example.org.helper",
               "GIT_CONFIG_VALUE_4": "!true",
               "GIT_CONFIG_KEY_5": "credential.https://example.org:8443.helper",
               "GIT_CONFIG_VALUE_5": "!true",
               "GIT_CONFIG_KEY_6": "credential.example.org.helper",
               "GIT_CONFIG_VALUE_6": "!true"}
        guard(env)
        for name, want in (("url.git@example.org:.insteadOf", "https://mirror.example.org/"),
                           ("url.https://example.org/.insteadOf", "https://mirror2.example.org/"),
                           ("url.https://example.org/@scope/.insteadOf",
                            "https://mirror3.example.org/"),
                           ("http.https://example.org/.sslVerify", "true"),
                           ("credential.https://example.org.helper", "!true"),
                           ("credential.https://example.org:8443.helper", "!true"),
                           ("credential.example.org.helper", "!true")):
            r = self.git(self.real, "config", "--get", name, env=env)
            self.assertEqual(r.stdout.strip(), want, r.stderr)

    def test_launch_refuses_incomplete_config_without_starting_an_agent(self):
        guard = load_guard(self.tmp / "guard.sh")
        tree = ast.parse(SCRIPT.read_text())
        tree.body = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run"]
        ns = {**guard.__globals__, "AGENTS": {"codex": ([], None)}, "sys": sys}
        exec(compile(tree, str(SCRIPT), "exec"), ns)  # no ACP SDK or agent process needed
        args = SimpleNamespace(agent="codex", auth=None, perm="deny", dir=str(self.real))
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"ACP_RUN_GIT_EMAIL": OPERATOR, "GIT_CONFIG_COUNT": "1",
                                          "GIT_CONFIG_VALUE_0": "private-value"}, clear=True), redirect_stderr(stderr):
            rc = asyncio.run(ns["run"](args, None, None, None))
        self.assertEqual(rc, 2)
        self.assertIn("missing GIT_CONFIG_KEY_0", stderr.getvalue())
        self.assertNotIn("private-value", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

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
        hook.write_text("#!/bin/sh\ntouch %s\n" % shlex.quote(str(self.real / "hook-ran")))
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
