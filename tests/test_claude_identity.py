#!/usr/bin/env python3
"""One Claude session id for every identity read (2026-11-02, PR 248 scope addition 3).

A /baton successor inherits its predecessor's CLAUDE_CODE_SESSION_ID, and a non-Claude agent started from a Claude shell inherits CLAUDE_PID. With
the session id now beating the pane match in fleet, a stale id would resolve a successor to its predecessor. The registry
(`<config>/sessions/<CLAUDE_PID>.json`, accepted only for an ancestor whose pid and procStart match) decides; the env var is the fallback.
Every pid, id and path here is fake; the process table and `ps` are replaced.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import test_relay_fallback as fb  # noqa: E402  # pyright: ignore[reportMissingImports]
import test_relay_sender_header as sh  # noqa: E402  # pyright: ignore[reportMissingImports]

relay, fleet = fb.relay, fb.fleet
cid = fleet._cid
STALE = "e236fcc3-287f-4c89-b6f4-435db7aef10c"    # the predecessor's id, inherited
LIVE = "7c96a0ca-bb70-4584-a254-f33bb399de58"     # the successor's own
CLAUDE_PID = 222
STAMP = "Mon Nov  2 09:00:00 2026"
OTHER_STAMP = "Mon Nov  2 07:00:00 2026"


class Base(fb.Harness):
    def setUp(self) -> None:
        super().setUp()
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
        relay.fleet.ancestors = lambda: set(self.ancestors)
        fleet._OWN_SID[0] = None
        self.addCleanup(fleet._OWN_SID.__setitem__, 0, None)

    def fake_ps(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout=self.live_start + "\n", stderr="")

    def register(self, pid: int = CLAUDE_PID, sid: str = LIVE, proc_start: str = STAMP) -> None:
        d = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "sessions"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{pid}.json").write_text(json.dumps({"pid": pid, "sessionId": sid, "procStart": proc_start}))
        fleet._OWN_SID[0] = None


class TestRegistryBeatsAStaleEnvironment(Base):
    def test_a_successor_with_its_predecessors_session_id_resolves_to_its_own_registry_id(self) -> None:
        self.register()
        self.assertEqual(cid.own_session_id(), LIVE)
        self.assertEqual(fleet.own_claude_session_id(), LIVE)
        label = relay.sender_name([])
        self.assertTrue(label.startswith(f"claude {LIVE[:8]}"), label)    # never the predecessor's label
        self.assertNotIn(STALE[:8], label)

    def test_the_predecessors_row_is_not_the_successors_self_row(self) -> None:
        self.register()
        row = fleet._rec(id=STALE[:8], agent="claude", sid=STALE)
        self.assertTrue(fleet.other_session(row))
        self.assertFalse(fleet.other_session(fleet._rec(id=LIVE[:8], agent="claude", sid=LIVE)))

    def test_without_a_registry_entry_the_env_var_is_the_fallback(self) -> None:
        self.assertEqual(cid.own_session_id(), STALE)
        self.assertEqual(fleet.own_claude_session_id(), STALE)

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
        self.assertIsNone(fleet.own_claude_session_id())
        self.assertNotIn(LIVE[:8], relay.sender_name([]))
        self.assertNotIn(STALE[:8], relay.sender_name([]))

    def test_its_own_pane_is_still_self_and_the_claude_rows_never_are(self) -> None:
        omp = fleet._rec(id="w20:p3", agent="omp")
        claude = fleet._rec(id=STALE[:8], agent="claude", sid=STALE)
        self.assertFalse(fleet.other_session(omp))
        self.assertFalse(fleet.other_session(claude))    # no id of its own to tell it apart: the pane decides, as before

    def test_an_unreadable_process_table_does_not_veto_the_env_var(self) -> None:
        self.ancestors = []
        self.assertEqual(cid.own_session_id(), STALE)

    def test_a_notice_sender_hides_its_ancestry_and_has_no_session(self) -> None:
        self.ancestors = [111, CLAUDE_PID]
        with relay.as_caller("relay", scrub=True):
            self.assertIsNone(fleet.own_claude_session_id())


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
        script = str(Path(__file__).resolve().parent.parent / "skills" / "session-finder" / "claude_identity.py")
        env = {"PATH": os.environ["PATH"], "CLAUDE_CODE_SESSION_ID": STALE}
        def run(env: dict[str, str]) -> tuple[int, str]:    # Popen: the Base patches subprocess.run itself (one shared module object)
            proc = subprocess.Popen([sys.executable, script], stdout=subprocess.PIPE, text=True, env=env)
            out, _ = proc.communicate()
            return proc.returncode, out.strip()
        self.assertEqual(run(env), (0, STALE))    # no CLAUDE_PID: the env var
        self.assertEqual(run({"PATH": os.environ["PATH"]}), (1, ""))


class TestThePaneCaseStillHolds(sh.TestOwnSessionIdBeatsThePane):
    """The e377e248 shape, unchanged, with the registry present: the child's own registry id keeps the pane's session from being self."""

    def setUp(self) -> None:
        super().setUp()
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp / "claude")
        os.environ["CLAUDE_PID"] = "222"
        d = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "sessions"
        d.mkdir(parents=True)
        (d / "222.json").write_text(json.dumps({"pid": 222, "sessionId": self.CHILD, "procStart": ""}))
        patcher = mock.patch.object(cid, "ancestor_pids", lambda: [5, 6, 222])
        patcher.start()
        self.addCleanup(patcher.stop)
        fleet.ancestors = lambda: {5, 6, 222}
        fleet._OWN_SID[0] = None

    def test_without_a_session_id_of_its_own_the_pane_match_still_holds(self) -> None:
        (Path(os.environ["CLAUDE_CONFIG_DIR"]) / "sessions" / "222.json").unlink()    # no registry entry, no env id: nothing to tell it apart
        del os.environ["CLAUDE_PID"]
        super().test_without_a_session_id_of_its_own_the_pane_match_still_holds()


if __name__ == "__main__":
    unittest.main()
