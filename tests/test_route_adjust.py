#!/usr/bin/env python3
"""route_adjust: hold, hysteresis, restoration, the frontier and omp rules (W8, 2026-11-12).

Offline: fixture quota dicts and mock services; no aiuse, no Paseo, no real state directory."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import route_adjust as ra
import route_agent as r

NOW = datetime(2026, 11, 12, 18, 0, tzinfo=UTC)


def svc(name: str, rank: int, kind: str = "code", **kw) -> r.Service:
    return r.Service(name, name, {kind: rank}, "subscription", judgment_tier=True, **kw)


def reading(remaining: float | None) -> dict:
    return {"remaining": remaining}


class Base(unittest.TestCase):
    kinds_services: tuple[r.Service, ...] = ()

    def setUp(self):
        self.a = svc("w8-a", 1)
        self.b = svc("w8-b", 5)
        self.services = self.kinds_services or (self.a, self.b)
        self.cfg = {**ra.DEFAULTS}
        stack = [
            mock.patch.object(r, "SERVICES", self.services),
            mock.patch.object(r, "BY_NAME", {s.name: s for s in self.services}),
            mock.patch.object(r, "discover", return_value=list(self.services)),
        ]
        for p in stack:
            p.start()
            self.addCleanup(p.stop)

    def run_adjust(self, kinds, quota, state=None, *, now=NOW, age=60.0, **kw):
        return ra.adjust(r, kinds, quota=quota, age=age, state=state or ra.empty_state(), now=now,
                         cfg=self.cfg, **kw)

    def pools(self, result):
        return [c.service.name if c else None for _, c, _ in result["rows"]]


class TestSettings(unittest.TestCase):
    def policy(self, adjust):
        return mock.Mock(POLICY={"routing": {"adjust": adjust}})

    def test_defaults_and_shipped_config(self):
        self.assertEqual(ra.settings(self.policy({}))["restore_margin"], 10.0)
        shipped = ra.settings(r)
        self.assertTrue(shipped["enabled"])
        self.assertIn("omp", shipped["never_target"])

    def test_omp_cannot_be_removed(self):
        self.assertIn("omp", ra.settings(self.policy({"never_target": ["other"]}))["never_target"])

    def test_bad_values_are_refused(self):
        for bad in ({"nope": 1}, {"enabled": "yes"}, {"restore_margin": -1}, {"min_dwell_seconds": True},
                    {"never_target": "omp"}):
            with self.assertRaises(ValueError, msg=bad):
                ra.settings(self.policy(bad))


class TestHoldAndRestore(Base):
    def test_first_route_is_logged_without_a_hold(self):
        res = self.run_adjust(["code"], {"w8-a": reading(80), "w8-b": reading(80)})
        self.assertEqual(self.pools(res), ["w8-a"])
        self.assertEqual([e["event"] for e in res["events"]], ["route"])
        self.assertEqual(res["held"], {})

    def test_dip_below_floor_switches_new_launches_and_logs_it(self):
        state = self.run_adjust(["code"], {"w8-a": reading(80), "w8-b": reading(80)})["state"]
        res = self.run_adjust(["code"], {"w8-a": reading(10), "w8-b": reading(80)}, state,
                              now=NOW + timedelta(minutes=5))
        self.assertEqual(self.pools(res), ["w8-b"])
        self.assertEqual(res["held"], {"code": ["w8-a"]})
        (event,) = res["events"]
        self.assertEqual((event["event"], event["from"], event["to"]), ("switch", "w8-a", "w8-b"))
        self.assertIn("10% left < floor 15%", event["why"])

    def test_hysteresis_then_restore(self):
        state = self.run_adjust(["code"], {"w8-a": reading(80), "w8-b": reading(80)})["state"]
        t1 = NOW + timedelta(minutes=5)
        state = self.run_adjust(["code"], {"w8-a": reading(10), "w8-b": reading(80)}, state, now=t1)["state"]
        # 18% clears the floor (15) but not floor + margin (25): still held, no flap.
        res = self.run_adjust(["code"], {"w8-a": reading(18), "w8-b": reading(80)}, state,
                              now=t1 + timedelta(hours=1))
        self.assertEqual(self.pools(res), ["w8-b"])
        self.assertEqual(res["events"], [])
        # 40% but inside the dwell: still held.
        res = self.run_adjust(["code"], {"w8-a": reading(40), "w8-b": reading(80)}, state,
                              now=t1 + timedelta(minutes=5))
        self.assertEqual(self.pools(res), ["w8-b"])
        # 40% after the dwell: restored, and the launch moves back.
        res = self.run_adjust(["code"], {"w8-a": reading(40), "w8-b": reading(80)}, state,
                              now=t1 + timedelta(minutes=20))
        self.assertEqual(self.pools(res), ["w8-a"])
        self.assertEqual(res["held"], {})
        (event,) = res["events"]
        self.assertEqual((event["event"], event["from"], event["to"]), ("restore", "w8-b", "w8-a"))

    def test_stale_snapshot_changes_no_hold(self):
        state = self.run_adjust(["code"], {"w8-a": reading(80), "w8-b": reading(80)})["state"]
        res = self.run_adjust(["code"], {"w8-a": reading(10), "w8-b": reading(80)}, state, age=99999)
        self.assertFalse(res["fresh"])
        self.assertEqual(res["held"], {})
        self.assertEqual(res["state"]["kinds"]["code"]["last"], "w8-b")  # routed around, no hold written
        # an empty snapshot is stale too
        self.assertFalse(self.run_adjust(["code"], {}, state)["fresh"])
        # and a stale snapshot never releases a hold
        held = self.run_adjust(["code"], {"w8-a": reading(10), "w8-b": reading(80)}, state)["state"]
        res = self.run_adjust(["code"], {"w8-a": reading(90), "w8-b": reading(80)}, held, age=None,
                              now=NOW + timedelta(hours=2))
        self.assertEqual(res["held"], {"code": ["w8-a"]})

    def test_unknown_reading_is_not_a_dip(self):
        state = self.run_adjust(["code"], {"w8-a": reading(80), "w8-b": reading(80)})["state"]
        res = self.run_adjust(["code"], {"w8-a": reading(None), "w8-b": reading(80)}, state)
        self.assertEqual(res["held"], {})

    def test_no_alternative_restores_early_instead_of_stranding(self):
        self.services = (self.a,)
        with mock.patch.object(r, "discover", return_value=[self.a]), \
             mock.patch.object(r, "SERVICES", (self.a,)), mock.patch.object(r, "BY_NAME", {"w8-a": self.a}):
            state = self.run_adjust(["code"], {"w8-a": reading(80)})["state"]
            state = self.run_adjust(["code"], {"w8-a": reading(10)}, state, now=NOW + timedelta(minutes=1))["state"]
            self.assertIn("w8-a", state["kinds"]["code"]["held"])
            res = self.run_adjust(["code"], {"w8-a": reading(18)}, state, now=NOW + timedelta(minutes=2))
        self.assertEqual(self.pools(res), ["w8-a"])
        self.assertEqual(res["held"], {})
        self.assertEqual(res["events"][0]["why"], "no acceptable alternative pool")

    def test_hold_expires(self):
        state = self.run_adjust(["code"], {"w8-a": reading(80), "w8-b": reading(80)})["state"]
        state = self.run_adjust(["code"], {"w8-a": reading(10), "w8-b": reading(80)}, state)["state"]
        res = self.run_adjust(["code"], {"w8-a": reading(18), "w8-b": reading(80)}, state, age=None,
                              now=NOW + timedelta(seconds=self.cfg["max_hold_seconds"] + 60))
        self.assertEqual(res["held"], {})
        self.assertIn("expire", [e["event"] for e in res["events"]])

    def test_holds_are_per_kind(self):
        a = r.Service("w8-a", "w8-a", {"code": 1, "bulk": 1}, "subscription", judgment_tier=True)
        b = r.Service("w8-b", "w8-b", {"code": 5, "bulk": 5}, "subscription", judgment_tier=True)
        with mock.patch.object(r, "discover", return_value=[a, b]), \
             mock.patch.object(r, "SERVICES", (a, b)), mock.patch.object(r, "BY_NAME", {"w8-a": a, "w8-b": b}):
            ok = {"w8-a": reading(80), "w8-b": reading(80)}
            state = self.run_adjust(["code"], ok)["state"]
            res = self.run_adjust(["code", "bulk"], {"w8-a": reading(10), "w8-b": reading(80)}, state)
        self.assertEqual(res["held"], {"code": ["w8-a"]})        # bulk never routed to a, so never held


class TestHardRules(Base):
    def setUp(self):
        self.astra = r.Service("w8-astra", "w8-astra", {"frontier": 1}, "subscription", judgment_tier=True,
                               models={"frontier": "gpt-6-astra --effort high"})
        self.opus = r.Service("w8-opus", "w8-opus", {"frontier": 4}, "subscription", judgment_tier=True,
                              models={"frontier": "claude-opus-5-5 --effort high"})
        self.kinds_services = (self.astra, self.opus)
        super().setUp()

    def test_frontier_is_never_silently_downgraded(self):
        state = self.run_adjust(["frontier"], {"w8-astra": reading(80), "w8-opus": reading(80)})["state"]
        self.assertEqual(state["kinds"]["frontier"]["last"], "w8-astra")
        res = self.run_adjust(["frontier"], {"w8-astra": reading(5), "w8-opus": reading(80)}, state)
        (kind, choice, refusal) = res["rows"][0]
        self.assertIsNone(choice)
        self.assertIn("refused, not downgraded", refusal)
        self.assertEqual(res["state"]["kinds"]["frontier"]["last"], "w8-astra")   # not moved onto Opus
        self.assertIn("refuse", [e["event"] for e in res["events"]])

    def test_frontier_to_another_frontier_pool_is_allowed(self):
        astra2 = r.Service("w8-astra2", "w8-astra2", {"frontier": 2}, "subscription", judgment_tier=True,
                           models={"frontier": "fable --effort high"})
        with mock.patch.object(r, "discover", return_value=[self.astra, astra2, self.opus]), \
             mock.patch.object(r, "SERVICES", (self.astra, astra2, self.opus)), \
             mock.patch.object(r, "BY_NAME", {s.name: s for s in (self.astra, astra2, self.opus)}):
            q = {"w8-astra": reading(80), "w8-astra2": reading(80), "w8-opus": reading(80)}
            state = self.run_adjust(["frontier"], q)["state"]
            res = self.run_adjust(["frontier"], {**q, "w8-astra": reading(5)}, state)
        self.assertEqual(self.pools(res), ["w8-astra2"])

    def test_omp_is_never_a_target(self):
        omp = svc("omp", 0)
        with mock.patch.object(r, "discover", return_value=[omp, self.a, self.b]), \
             mock.patch.object(r, "SERVICES", (omp, self.a, self.b)), \
             mock.patch.object(r, "BY_NAME", {s.name: s for s in (omp, self.a, self.b)}):
            res = self.run_adjust(["code"], {"omp": reading(99), "w8-a": reading(80), "w8-b": reading(80)})
        self.assertEqual(self.pools(res), ["w8-a"])

    def test_omp_model_or_agent_is_refused_even_if_routed(self):
        class Fake:
            service = svc("pi-like", 1, agent="omp")
            model = "x"
        self.assertIn("never_target", ra._refusal(r, "code", Fake(), self.cfg))

    def refusal(self, name, model, **kw):
        choice = r.Choice(svc(name, 1, **kw), 80.0, 1.0, model=model, kind="code")
        return ra._refusal(r, "code", choice, self.cfg)

    def test_never_target_is_exact_not_a_substring(self):
        # A1: "composer" contains "omp"; the Pi Composer pool must stay routable.
        self.assertIsNone(self.refusal("cursor", "cursor/composer-2.5", agent="pi"))
        self.assertIsNone(self.refusal("cursor", "composer-2.5"))
        self.assertIn("never_target", self.refusal("x", "omp/claude-opus"))        # provider prefix
        self.assertIn("never_target", self.refusal("omp", "m"))                    # name
        self.assertIn("never_target", self.refusal("x", "m", agent="omp"))         # agent
        self.assertIn("never_target", self.refusal("omp-dev", "m"))                # family name

    def test_disabled_still_enforces_both_hard_rules(self):
        # A9: enabled = false is plan with no state, not plan without the guards.
        self.cfg = {**ra.DEFAULTS, "enabled": False}
        res = self.run_adjust(["frontier"], {"w8-astra": reading(80), "w8-opus": reading(80)})
        self.assertEqual(res["held"], {})                      # no holds; the CLI persists nothing when disabled
        self.assertEqual(res["events"], [])
        self.assertEqual(self.pools(res), ["w8-astra"])
        res = self.run_adjust(["frontier"], {"w8-astra": reading(5), "w8-opus": reading(80)})
        self.assertIn("refused, not downgraded", res["rows"][0][2])


class TestRepairs(Base):
    """Regression tests for the adversary round (A2-A10)."""

    def ok(self):
        return {"w8-a": reading(80), "w8-b": reading(80)}

    def test_multi_slice_kind_tracks_first_slice_and_logs_once(self):  # A2
        a = svc("w8-a", 1, max_parallel=1)
        with mock.patch.object(r, "discover", return_value=[a, self.b]), \
             mock.patch.object(r, "SERVICES", (a, self.b)), \
             mock.patch.object(r, "BY_NAME", {"w8-a": a, "w8-b": self.b}):
            res = self.run_adjust(["code", "code"], self.ok())
            self.assertEqual(self.pools(res), ["w8-a", "w8-b"])
            self.assertEqual([e["event"] for e in res["events"]], ["route"])
            state = res["state"]
            res = self.run_adjust(["code", "code"], self.ok(), state, now=NOW + timedelta(minutes=1))
            self.assertEqual(res["events"], [])                      # steady state: no change lines
            self.assertEqual(res["state"]["kinds"]["code"]["last"], "w8-a")
            res = self.run_adjust(["code", "code"], {"w8-a": reading(10), "w8-b": reading(80)}, state)
            self.assertEqual(res["held"], {"code": ["w8-a"]})        # the first slice's pool gets hysteresis

    def test_restore_margin_sits_on_the_binding_estimate_floor(self):  # A3
        def floor(svc_, kind, info, repo=None):
            return (60.0 if svc_.name == "w8-a" else 0.0), None
        with mock.patch.object(r, "estimate_floor", side_effect=floor):
            state = self.run_adjust(["code"], self.ok())["state"]
            state = self.run_adjust(["code"], {"w8-a": reading(58), "w8-b": reading(80)}, state,
                                    now=NOW + timedelta(minutes=1))["state"]
            later = NOW + timedelta(hours=1)
            res = self.run_adjust(["code"], {"w8-a": reading(62), "w8-b": reading(80)}, state, now=later)
            self.assertEqual(self.pools(res), ["w8-b"])                # 62 clears 60 but not 60 + 10
            res = self.run_adjust(["code"], {"w8-a": reading(75), "w8-b": reading(80)}, state, now=later)
            self.assertEqual(self.pools(res), ["w8-a"])

    def test_hold_does_not_move_the_quality_band(self):  # A4
        far = svc("w8-far", 12)
        with mock.patch.object(r, "discover", return_value=[self.a, far]), \
             mock.patch.object(r, "SERVICES", (self.a, far)), \
             mock.patch.object(r, "BY_NAME", {"w8-a": self.a, "w8-far": far}), \
             mock.patch.object(r, "QUALITY_MAX_RANK_GAP", {"code": 10}):
            q = {"w8-a": reading(10), "w8-far": reading(80)}
            self.assertIsNone(r.plan(["code"], quota=q)[0][1])          # plain plan: far is outside the band
            state = self.run_adjust(["code"], {"w8-a": reading(80), "w8-far": reading(80)})["state"]
            res = self.run_adjust(["code"], q, state)
        self.assertEqual(self.pools(res), [None])                       # adjust keeps the band
        self.assertEqual(res["held"], {"code": ["w8-a"]})
        self.assertIn("hold", [e["event"] for e in res["events"]])      # A10a: a hold with no route line

    def test_refused_slice_takes_no_wave_slot_and_hold_yields_to_frontier(self):  # A5, A10d
        astra = r.Service("w8-astra", "w8-astra", {"frontier": 1}, "subscription", judgment_tier=True,
                          models={"frontier": "gpt-6-astra --effort high"})
        opus = r.Service("w8-opus", "w8-opus", {"frontier": 4}, "subscription", judgment_tier=True,
                         models={"frontier": "claude-opus-5-5 --effort high"})
        with mock.patch.object(r, "discover", return_value=[astra, opus]), \
             mock.patch.object(r, "SERVICES", (astra, opus)), \
             mock.patch.object(r, "BY_NAME", {"w8-astra": astra, "w8-opus": opus}):
            good = {"w8-astra": reading(80), "w8-opus": reading(80)}
            state = self.run_adjust(["frontier"], good)["state"]
            held = self.run_adjust(["frontier"], {"w8-astra": reading(5), "w8-opus": reading(80)}, state)["state"]
            self.assertIn("w8-astra", held["kinds"]["frontier"]["held"])
            # astra is back at 80% but still inside the dwell: the hold yields rather than refuse
            res = self.run_adjust(["frontier"], good, held, now=NOW + timedelta(minutes=1))
            self.assertEqual(self.pools(res), ["w8-astra"])
            self.assertIsNone(res["rows"][0][2])
            self.assertEqual(res["events"][0]["event"], "restore")
            # a refusal logs once, not on every call
            down = {"w8-astra": reading(5), "w8-opus": reading(80)}
            first = self.run_adjust(["frontier"], down, state)
            again = self.run_adjust(["frontier"], down, first["state"], now=NOW + timedelta(minutes=1))
            self.assertIn("refuse", [e["event"] for e in first["events"]])
            self.assertNotIn("refuse", [e["event"] for e in again["events"]])
            self.assertIsNotNone(again["rows"][0][2])

    def test_refused_choice_does_not_consume_a_slot(self):  # A10d
        astra = r.Service("w8-astra", "w8-astra", {"frontier": 1}, "subscription", judgment_tier=True,
                          max_parallel=1, models={"frontier": "gpt-6-astra --effort high"})
        refusals: list = []
        with mock.patch.object(r, "discover", return_value=[astra]), \
             mock.patch.object(r, "SERVICES", (astra,)), mock.patch.object(r, "BY_NAME", {"w8-astra": astra}):
            rows = r.plan(["frontier", "frontier"], quota={"w8-astra": reading(80)},
                          reject=lambda k, c: "no" if not refusals else None, refusals=refusals)
        self.assertEqual([c is None for _, c in rows], [True, False])   # the refused first slice freed the cap
        self.assertEqual(refusals, ["no", None])

    def test_bad_held_type_reads_as_no_holds(self):  # A6
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            for bad in (["x"], "x", 3, None):
                path.write_text(json.dumps({"schema_version": 1, "kinds": {"code": {"held": bad}}}))
                self.assertEqual(ra.load_state(path)["kinds"]["code"]["held"], {})

    def test_future_timestamp_expires(self):  # A7
        state = ra.empty_state()
        state["kinds"]["code"] = {"last": "w8-b", "refused": None, "held": {
            "w8-a": {"since": ra._iso(NOW + timedelta(days=1)), "why": "x"}}}
        res = self.run_adjust(["code"], self.ok(), state)
        self.assertEqual(res["held"], {})
        self.assertIn("expire", [e["event"] for e in res["events"]])

    def test_holds_are_scoped_to_the_repo(self):  # A8
        state = self.run_adjust(["code"], self.ok(), repo="tendcf")["state"]
        self.assertIn("tendcf:code", state["kinds"])
        state = self.run_adjust(["code"], {"w8-a": reading(10), "w8-b": reading(80)}, state, repo="tendcf")["state"]
        other = self.run_adjust(["code"], self.ok(), state, repo=None)
        self.assertEqual(other["held"], {})                              # another repo's hold does not apply
        self.assertEqual(self.pools(other), ["w8-a"])
        mine = self.run_adjust(["code"], self.ok(), state, repo="tendcf", now=NOW + timedelta(minutes=1))
        self.assertEqual(mine["held"], {"code": ["w8-a"]})


class TestStateAndLog(unittest.TestCase):
    def test_lock_times_out_instead_of_blocking(self):  # A11b
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            with ra.locked(Path(tmp)):
                fd = os.open(Path(tmp) / "state.lock", os.O_WRONLY)
                try:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaises(TimeoutError):
                        with ra.locked(Path(tmp), timeout=0.2):
                            pass
                finally:
                    os.close(fd)

    def test_symlinked_log_and_relative_dir_are_refused(self):  # A11c, A11d
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "elsewhere"
            target.write_text("")
            (Path(tmp) / "changes.jsonl").symlink_to(target)
            with self.assertRaises(OSError):
                ra.log_events(Path(tmp), [{"event": "a"}])
            self.assertEqual(target.read_text(), "")
        with mock.patch.dict(os.environ, {"ADE_ROUTE_ADJUST_DIR": "relative/dir"}):
            with self.assertRaises(ValueError):
                ra.state_dir()

    def test_roundtrip_and_corruption_reads_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "state.json"
            state = {"schema_version": 1, "kinds": {"code": {"last": "x", "refused": None, "held": {
                "y": {"since": "2026-11-12T18:00:00Z", "why": "w"}}}}}
            ra.save_state(path, state)
            self.assertEqual(ra.load_state(path), state)
            self.assertEqual([p.name for p in path.parent.iterdir()], ["state.json"])   # no temp left
            path.write_text("{not json")
            self.assertEqual(ra.load_state(path), ra.empty_state())
            path.write_text(json.dumps({"schema_version": 99, "kinds": {}}))
            self.assertEqual(ra.load_state(path), ra.empty_state())
            path.write_text(json.dumps({"schema_version": 1, "kinds": {"code": {"held": {"y": {"since": "junk"}}}}}))
            self.assertEqual(ra.load_state(path)["kinds"]["code"]["held"], {})

    def test_one_log_line_per_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            ra.log_events(Path(tmp), [{"event": "a"}, {"event": "b"}])
            ra.log_events(Path(tmp), [])
            ra.log_events(Path(tmp), [{"event": "c"}])
            lines = (Path(tmp) / "changes.jsonl").read_text().splitlines()
            self.assertEqual([json.loads(x)["event"] for x in lines], ["a", "b", "c"])


class TestPlanKindExclude(Base):
    def test_soft_exclude(self):
        q = {"w8-a": reading(80), "w8-b": reading(80)}
        rows = r.plan(["code"], quota=q, kind_exclude={"code": {"w8-a"}})
        self.assertEqual(rows[0][1].service.name, "w8-b")
        rows = r.plan(["code"], quota=q, kind_exclude={"code": {"w8-a", "w8-b"}})
        self.assertEqual(rows[0][1].service.name, "w8-a")     # nothing else: the hold yields to the best
        rows = r.plan(["code"], quota=q)
        self.assertEqual(rows[0][1].service.name, "w8-a")


class TestCli(Base):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ADE_ROUTE_ADJUST_DIR": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.quota = {"w8-a": reading(80), "w8-b": reading(80)}
        for p in (mock.patch.object(r, "load_snapshot", side_effect=lambda *a, **k: (self.quota, 60.0)),
                  mock.patch.object(r, "operator_disabled", return_value=set()),
                  mock.patch.object(r, "repo_of", return_value=None),
                  mock.patch.object(r, "quota_source_info", return_value={})):
            p.start()
            self.addCleanup(p.stop)

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = r.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_switch_is_persisted_logged_and_dry_run_writes_nothing(self):
        state = Path(self.tmp.name) / "state.json"
        code, out, _ = self.call("adjust", "--kinds", "code", "--dry-run", "--json")
        self.assertEqual(code, 0)
        self.assertFalse(state.exists())
        self.assertEqual(json.loads(out)["slices"][0]["service"], "w8-a")
        self.call("adjust", "--kinds", "code")
        self.quota = {"w8-a": reading(10), "w8-b": reading(80)}
        code, out, err = self.call("adjust", "--kinds", "code", "--json")
        doc = json.loads(out)
        self.assertEqual((code, doc["slices"][0]["service"], doc["held"]), (0, "w8-b", {"code": ["w8-a"]}))
        self.assertIn('"event": "switch"', err)
        log = (Path(self.tmp.name) / "changes.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(x)["event"] for x in log], ["route", "switch"])
        code, out, _ = self.call("adjust", "--status")
        self.assertEqual(json.loads(out)["kinds"]["code"]["held"].keys(), {"w8-a"})

    def test_refusal_exit_code(self):
        astra = r.Service("w8-astra", "w8-astra", {"frontier": 1}, "subscription", judgment_tier=True,
                          models={"frontier": "gpt-6-astra --effort high"})
        opus = r.Service("w8-opus", "w8-opus", {"frontier": 4}, "subscription", judgment_tier=True,
                         models={"frontier": "claude-opus-5-5 --effort high"})
        self.quota = {"w8-astra": reading(80), "w8-opus": reading(80)}
        with mock.patch.object(r, "discover", return_value=[astra, opus]), \
             mock.patch.object(r, "SERVICES", (astra, opus)), \
             mock.patch.object(r, "BY_NAME", {"w8-astra": astra, "w8-opus": opus}):
            self.assertEqual(self.call("adjust", "--kinds", "frontier")[0], 0)
            self.quota = {"w8-astra": reading(5), "w8-opus": reading(80)}
            code, out, _ = self.call("adjust", "--kinds", "frontier")
        self.assertEqual(code, r.ADJUST_EXIT_REFUSED)
        self.assertIn("REFUSED", out)

    def test_lock_timeout_plans_read_only(self):
        with mock.patch.object(ra, "locked", side_effect=TimeoutError("busy")):
            code, out, err = self.call("adjust", "--kinds", "code")
        self.assertEqual(code, 0)
        self.assertIn("w8-a", out)
        self.assertIn("planning read-only", err)
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_disabled_is_plain_plan(self):
        with mock.patch.object(ra, "settings", return_value={**ra.DEFAULTS, "enabled": False}):
            code, out, _ = self.call("adjust", "--kinds", "code")
        self.assertEqual(code, 0)
        self.assertIn("w8-a", out)
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_bad_kind_and_missing_kinds(self):
        for argv in (("adjust", "--kinds", "nope"), ("adjust",)):
            with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                r.main(list(argv))


if __name__ == "__main__":
    unittest.main()
