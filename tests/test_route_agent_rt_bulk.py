"""rt-bulk (2026-11-15): `route` passes over a pool with no model profile for the kind (its dispatch line would carry a
`--provider` placeholder and `dispatch_warnings` would block the slice); the placeholder survives only when no pool that
can take the kind has a profile."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import route_agent as r  # noqa: E402

LEAD = "11111111-2222-3333-4444-555555555555"
KINDS = ("bulk", "code", "research")


def _svc(name, models, rank=1):
    return r.Service(name, name, {k: rank for k in KINDS}, "subscription", models=dict(models), max_parallel=4)


def _route(kind, services, quota=None, **kw):
    with mock.patch.object(r, "discover", lambda q=None: list(services)):
        return r.route(kind, quota=quota or {}, **kw)


def _plan(kinds, services):
    with mock.patch.object(r, "discover", lambda q=None: list(services)):
        return r.plan(kinds, quota={})


def test_first_pool_without_a_profile_is_skipped_and_named():
    bare, good = _svc("aaa-bare", {}), _svc("zzz-good", {"bulk": "m1x"})
    c = _route("bulk", [bare, good])
    assert c.service.name == "zzz-good"
    assert c.skipped == ["aaa-bare: no model profile for bulk"]
    assert "<id from" not in c.dispatch
    assert [w for w in dataclasses.replace(c, placement=r.Placement(lead=LEAD, slice="s", cwd="/x")).dispatch_warnings
            if "no model profile" in w] == []


def test_every_pool_without_a_profile_keeps_the_placeholder_and_the_warning():
    c = _route("bulk", [_svc("aaa-bare", {}), _svc("bbb-bare", {})])
    assert c is not None and c.service.name == "aaa-bare"
    assert "<id from" in c.dispatch
    placed = dataclasses.replace(c, placement=r.Placement(lead=LEAD, slice="s", cwd="/x"))
    assert any("no model profile for bulk" in w for w in placed.dispatch_warnings)


def test_a_full_profiled_pool_queues_instead_of_handing_out_a_placeholder():
    bare, full = _svc("aaa-bare", {}), _svc("zzz-full", {"bulk": "m1x"})
    assert _route("bulk", [bare, full], quota={"zzz-full": {"remaining": 0.0}}) is None


def test_other_kinds_with_a_profile_are_unchanged():
    bare = _svc("aaa-bare", {})
    good = _svc("zzz-good", {"bulk": "m1x", "code": "c1", "research": "v1"})
    for kind in ("code", "research"):
        c = _route(kind, [bare, good])
        assert c.service.name == "zzz-good" and c.skipped == ["aaa-bare: no model profile for " + kind]


def test_explicit_exclude_still_applies_and_does_not_report_a_skip_for_an_excluded_pool():
    bare, good = _svc("aaa-bare", {}), _svc("zzz-good", {"bulk": "m1x"})
    assert _route("bulk", [bare, good], exclude={"zzz-good"}) is None
    assert _route("bulk", [bare, good], exclude={"aaa-bare"}).skipped == []


def test_plan_carries_the_skip():
    rows = _plan(["bulk"], [_svc("aaa-bare", {}), _svc("zzz-good", {"bulk": "m1x"})])
    (kind, c), = rows
    assert c.service.name == "zzz-good" and c.skipped


def test_a_full_held_or_disabled_profiled_pool_queues_instead_of_handing_out_the_placeholder():
    """adversary M1 (head 19f4d9eb): `exclude` (wave cap, disabled pools) and `avoid` (adjust holds) ran before the profile check."""
    bare, good = _svc("aaa-bare", {}), _svc("zzz-good", {"bulk": "m1x"})
    assert _route("bulk", [bare, good], exclude={"zzz-good"}) is None
    assert _route("bulk", [bare, good], avoid={"zzz-good"}) is None


def test_wave_cap_queues_the_next_bulk_slice_not_the_placeholder():
    bare = _svc("aaa-bare", {})
    good = r.Service("zzz-good", "zzz-good", {k: 1 for k in KINDS}, "subscription", models={"bulk": "m1x"}, max_parallel=1)
    rows = _plan(["bulk", "bulk"], [bare, good])
    assert rows[0][1].service.name == "zzz-good" and rows[1][1] is None
