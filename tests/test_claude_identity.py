#!/usr/bin/env python3
"""One Claude session id for every identity read (2026-11-02, PR 248 scope addition 3; autorename got the same rule in PR 259).

A /baton successor inherits its predecessor's CLAUDE_CODE_SESSION_ID, and a non-Claude agent started from a Claude shell inherits CLAUDE_PID. The
registry (`<config>/sessions/<CLAUDE_PID>.json`, accepted only for an ancestor whose pid and procStart match) decides; the env var is the fallback.
Every pid, id and path here is fake; the process table and `ps` are replaced.

2026-11-06 (docs/slim E3): bin/claude_identity.py (moved from skills/session-finder/, a forwarding stub stays there for one cycle). The relay.py
and fleet.py halves of these tests went with relay.py's old routes (the harness was test_relay_fallback.py); the resolver, ade_claims, autorename,
the script and the stub are tested here on their own harness.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import claude_identity as cid  # noqa: E402  # the module ade_claims and autorename import by name: one object, so the patches below reach them

STALE = "e236fcc3-287f-4c89-b6f4-435db7aef10c"    # the predecessor's id, inherited
LIVE = "7c96a0ca-bb70-4584-a254-f33bb399de58"     # the successor's own
CLAUDE_PID = 222
STAMP = "Mon Nov  2 09:00:00 2026"
OTHER_STAMP = "Mon Nov  2 07:00:00 2026"


class Base(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ)    # whatever session runs the tests is not under test
        patcher.start()
        self.addCleanup(patcher.stop)
        for k in ("PASEO_AGENT_ID", "ADE_CLAIM_ID", "CLAUDE_CODE_SESSION_ID", "CLAUDE_PID"):
            os.environ.pop(k, None)
        self.tmp = Path(tempfile.mkdtemp(prefix="claude-identity-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp / "claude")
        os.environ["CLAUDE_CODE_SESSION_ID"] = STALE
        os.environ["CLAUDE_PID"] = str(CLAUDE_PID)
        self.ancestors = [111, CLAUDE_PID, 333]
        self.live_start = STAMP
        patchers = [mock.patch.object(cid, "ancestor_pids", lambda: list(self.ancestors)),
                    mock.patch.object(cid.subprocess, "run", self.fake_ps),
                    mock.patch.object(cid, "pid_alive", lambda pid: True)]    # the fake Claude pids are not real processes
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def fake_ps(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout=self.live_start + "\n", stderr="")

    def register(self, pid: int = CLAUDE_PID, sid: str = LIVE, proc_start: str = STAMP) -> None:
        d = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "sessions"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{pid}.json").write_text(json.dumps({"pid": pid, "sessionId": sid, "procStart": proc_start}))


class TestRegistryBeatsAStaleEnvironment(Base):
    def test_a_successor_with_its_predecessors_session_id_resolves_to_its_own_registry_id(self) -> None:
        self.register()
        self.assertEqual(cid.own_session_id(), LIVE)

    def test_without_a_registry_entry_the_env_var_is_the_fallback(self) -> None:
        self.assertEqual(cid.own_session_id(), STALE)

    def test_a_recycled_pid_with_another_proc_start_falls_back_to_the_env_var(self) -> None:
        self.register(proc_start=OTHER_STAMP)    # a crashed Claude left 222.json; pid 222 now belongs to a later process
        self.assertIsNone(cid.registered_session_id())
        self.assertEqual(cid.own_session_id(), STALE)

    def test_a_registry_file_naming_another_pid_or_a_non_uuid_is_not_trusted(self) -> None:
        self.register()
        path = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "sessions" / f"{CLAUDE_PID}.json"
        for bad in ({"pid": 999, "sessionId": LIVE}, {"pid": CLAUDE_PID, "sessionId": "not-a-uuid"}, ["x"]):
            with self.subTest(bad=bad):
                path.write_text(json.dumps(bad))
                self.assertIsNone(cid.registered_session_id())


class TestAnInheritedClaudePidThatIsNotAnAncestor(Base):
    """An omp or codex started from a Claude shell carries that Claude's CLAUDE_PID and CLAUDE_CODE_SESSION_ID, neither of which is its own."""

    def setUp(self) -> None:
        super().setUp()
        self.ancestors = [111, 444, 555]    # the Claude (222) is not above this process
        self.register()                      # ... and its registry file is live and valid

    def test_it_is_not_taken_for_that_claude(self) -> None:
        self.assertIsNone(cid.registered_session_id())
        self.assertIsNone(cid.own_session_id())    # the inherited env var is distrusted too: CLAUDE_PID is provably not above us

    def test_an_unreadable_process_table_does_not_veto_the_env_var(self) -> None:
        self.ancestors = []
        self.assertEqual(cid.own_session_id(), STALE)


class TestAutorenameAndAdeClaimsShareIt(Base):
    def test_ade_claims_names_the_registry_id_for_its_own_environment_but_reads_a_given_one_as_is(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("ade_claims_t", Path(__file__).resolve().parent.parent / "bin" / "ade_claims.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod    # dataclasses look their module up here
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(mod)
        self.register()
        os.environ.pop("ADE_CLAIM_ID", None)
        os.environ.pop("PASEO_AGENT_ID", None)
        self.assertEqual(mod.caller_ident(os.environ), LIVE)    # callers pass os.environ itself
        self.assertEqual(mod.caller_ident(), LIVE)
        self.assertEqual(mod.caller_ident({"CLAUDE_CODE_SESSION_ID": STALE}), STALE)    # an explicit mapping is read as given

    def ade_claims(self) -> Any:
        import importlib.util
        spec = importlib.util.spec_from_file_location("ade_claims_t2", Path(__file__).resolve().parent.parent / "bin" / "ade_claims.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(mod)
        os.environ.pop("ADE_CLAIM_ID", None)
        os.environ.pop("PASEO_AGENT_ID", None)
        return mod

    def test_an_orphaned_background_job_keeps_the_owner_its_correct_env_pair_names(self) -> None:
        """PR 248 adversary r1b A1: `nohup sh -c 'git push' &` from a Claude Bash call is reparented to launchd, so CLAUDE_PID is no ancestor, yet its
        CLAUDE_CODE_SESSION_ID is right. caller_ident must not drop it (the owner's push was refused 77)."""
        mod = self.ade_claims()
        os.environ["CLAUDE_CODE_SESSION_ID"] = LIVE
        self.ancestors = [86395]    # reparented: the Claude (222) is no ancestor
        self.assertEqual(mod.caller_ident(os.environ), LIVE)
        self.assertEqual(cid.owner_session_id(), LIVE)
        self.register()    # the Claude that exported the pair is alive and registered: same answer
        with mock.patch.object(cid, "pid_alive", lambda pid: True):
            self.assertEqual(mod.caller_ident(os.environ), LIVE)

    def test_a_successors_orphaned_job_keeps_the_successors_registry_id_while_its_claude_lives(self) -> None:
        """local-review r2: the detached job's env carries the predecessor's stale id; the live Claude CLAUDE_PID names still proves the real one,
        so `new` (registry id) and the job's guard agree. Once that Claude is gone, the env var stands."""
        mod = self.ade_claims()
        self.register()
        self.ancestors = [86395]    # detached: no ancestry to prove anything
        with mock.patch.object(cid, "pid_alive", lambda pid: True):
            self.assertEqual(mod.caller_ident(os.environ), LIVE)
            self.assertEqual(cid.owner_session_id(), LIVE)
            self.assertIsNone(cid.own_session_id())    # an identity LABEL still needs the ancestor proof
        with mock.patch.object(cid, "pid_alive", lambda pid: False):
            self.assertEqual(cid.owner_session_id(), STALE)
        self.register(proc_start=OTHER_STAMP)    # pid reuse: the file names another process start
        with mock.patch.object(cid, "pid_alive", lambda pid: True):
            self.assertEqual(cid.owner_session_id(), STALE)

    def test_a_successor_creating_its_claim_with_the_inherited_env_id_is_recorded_and_checked_under_its_own(self) -> None:
        """r1b A2: `new --owner-session "$CLAUDE_CODE_SESSION_ID"` and the guard's caller_ident must agree in the /baton-successor case."""
        mod = self.ade_claims()
        self.register()
        self.assertEqual(mod._owner_session_arg(STALE), LIVE)    # the raw env id becomes the registry's
        self.assertEqual(mod._owner_session_arg("some-other-session"), "some-other-session")    # any other value is kept
        self.assertEqual(mod._owner_session_arg(None), None)
        self.assertEqual(mod.caller_ident(os.environ), LIVE)

    def test_the_owner_helper_is_a_script_for_the_skills(self) -> None:
        env = {"PATH": os.environ["PATH"], "CLAUDE_CODE_SESSION_ID": STALE, "CLAUDE_CONFIG_DIR": str(self.tmp / "claude")}
        def run(script: Path, env: dict[str, str]) -> tuple[int, str]:    # Popen: the Base patches subprocess.run itself (one shared module object)
            proc = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True, env=env)
            out, _ = proc.communicate()
            return proc.returncode, out.strip()
        for script in (ROOT / "bin" / "claude_identity.py", ROOT / "skills" / "session-finder" / "claude_identity.py"):    # the new path and the stub
            with self.subTest(script=script):
                self.assertEqual(run(script, env), (0, STALE))    # no CLAUDE_PID: the env var
                self.assertEqual(run(script, {"PATH": os.environ["PATH"], "CLAUDE_CONFIG_DIR": env["CLAUDE_CONFIG_DIR"]}), (1, ""))

    def test_the_old_path_stub_imports_the_moved_module(self) -> None:
        """One cycle (removed at the latest 2026-11-20): an importer that still puts skills/session-finder on sys.path gets bin/'s module."""
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import claude_identity as c; "
                "print(c.__file__); print(callable(c.owner_session_id))")
        proc = subprocess.Popen([sys.executable, "-c", code, str(ROOT / "skills" / "session-finder")], stdout=subprocess.PIPE, text=True)
        out, _ = proc.communicate()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(out.split(), [str((ROOT / "bin" / "claude_identity.py").resolve()), "True"])

    def test_autorename_uses_the_same_helper(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("autorename_t", Path(__file__).resolve().parent.parent / "skills/autorename/autorename.py")
        assert spec and spec.loader
        ar = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ar)
        self.register()
        with mock.patch.object(ar, "ancestor_pids", lambda: list(self.ancestors)):
            self.assertEqual(ar.registered_claude_session_id(), LIVE)
        self.assertIs(ar.claude_identity.registered_session_id, cid.registered_session_id)


if __name__ == "__main__":
    unittest.main()
