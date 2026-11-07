"""Shared pytest setup for the djbclark-ade tests."""
import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Never make fixtures inside the real dispatch state root. A slice that ran these tests with
# TMPDIR under its task dir (2026-10-14, gnu-normalize) left 80 acpd-* fixture trees there, whose
# fake jobs/*.json records reap, the in-flight cap and dispatch history then scanned as real.
_STATE = (Path.home() / ".local/state/bigteam").resolve()
for _var in ("TMPDIR", "TEMP", "TMP"):
    if os.environ.get(_var) and Path(os.environ[_var]).resolve().is_relative_to(_STATE):
        del os.environ[_var]
tempfile.tempdir = None

# acp-dispatch holds a slice's start while the real machine is overloaded
# (bin/acp-dispatch wait_for_capacity). Tests must not depend on the host's
# load: with it on, a busy machine made dispatch tests wait and fail
# (2026-10-12). test_acp_dispatch_gate.py exercises the gate directly.
os.environ.setdefault("ACP_DISPATCH_NO_GATE", "1")
# The same for the load gate (`load-watch admit`, 2026-10-19): it waits up to 30 min on a hot host and
# refuses with 75. test_acp_dispatch_load_gate.py turns it on per test with a fake load-watch.
os.environ["ACP_DISPATCH_NO_LOAD_GATE"] = "1"  # unconditional: an outer "" or "0" must not turn the real 30-min gate on
# A quota stop schedules an in-place resume with `launchctl submit` (2026-10-18). No test may
# leave a real launchd job behind: test_acp_dispatch.py gives finalize a fake launchctl that
# records its arguments; anything else gets a no-op.
os.environ.setdefault("ACP_DISPATCH_LAUNCHCTL", "/usr/bin/true")
# bin/ade_sched.py (bin/ade-sched, 2026-11-04) installs jobs on launchd, systemd or cron. No test may touch the real ones:
# every scheduler binary is a no-op and the agent/unit dirs and the crontab lock live in a throwaway directory.
# Unconditional: an outer value must not point the suite at a real scheduler or ~/.config/systemd/user.
# tests/test_ade_sched.py passes fake binaries and dirs per test.
for _var in ("ADE_SCHED_LAUNCHCTL", "ADE_SCHED_SYSTEMCTL", "ADE_SCHED_LOGINCTL", "ADE_SCHED_CRONTAB"):
    os.environ[_var] = "/usr/bin/true"
_SCHED_ROOT = Path(tempfile.mkdtemp(prefix="ade-sched-suite-"))
atexit.register(shutil.rmtree, _SCHED_ROOT, ignore_errors=True)
os.environ["ADE_SCHED_LAUNCH_AGENTS"] = str(_SCHED_ROOT / "LaunchAgents")
os.environ["ADE_SCHED_UNIT_DIR"] = str(_SCHED_ROOT / "systemd-user")
os.environ["ADE_SCHED_LOCK"] = str(_SCHED_ROOT / "ade-sched.lock")
# `reap` throttles dir sweeps younger than 60 s through a machine-wide stamp (2026-10-18).
# Off in tests: dir sweeps must always run and must never touch the real machine's stamp;
# test_acp_dispatch_waiter.py turns the throttle on explicitly per test.
os.environ.setdefault("ACP_DISPATCH_REAP_MIN_INTERVAL", "0")
# route_agent.load_snapshot() runs `aiuse --available --json` unless a snapshot is pinned (2026-10-20).
# Off in tests so the suite never depends on, or spawns, the host's real aiuse;
# test_route_agent.py's TestQuotaFromAiuseAvailable turns it on per test.
os.environ.setdefault("ROUTE_AGENT_AIUSE", "off")
# route_agent.pool_fits reads the machine's measured astra slices (kind_rows) for every service and kind's estimate, as acp-dispatch's
# estimate_pct does (2026-11-01). Off in tests so no result depends on the host's dispatch history;
# test_argon_frontier.py turns it on per test against a temp state root.
os.environ.setdefault("ROUTE_AGENT_CALIBRATED_FLOOR", "off")
# route_agent.omp_anthropic_ready() reads the host's omp login (~/.omp/agent/agent.db) unless forced (2026-10-20,
# docs/queue.md item 6). With a working login omp joins every roster as an unmeasured code/bulk pool and changed
# the answer of three tests that pass on CI, which has no login. Off in tests; TestOmpCreditsTier and
# TestOmpReadyRoster turn it on per test with mock.patch.dict.
# An outer "0" or "1" wins on purpose (a full-suite run with ROUTE_AGENT_OMP_READY=1 is the omp-ready
# check; adversary 2026-10-20). Any other value, "" included, would send the probe to the real login.
if os.environ.get("ROUTE_AGENT_OMP_READY", "").strip().lower() not in ("0", "1"):
    os.environ["ROUTE_AGENT_OMP_READY"] = "0"
# route_agent.governor_hold() reads the fleet governor's state (2026-10-23): a real tight/critical level on the host
# would drop claude from every code/bulk/research/mechanical route and change the answer of unrelated tests.
# Pinned to a missing file unconditionally; TestGovernorHold points it at a fixture per test.
os.environ["CLAUDE_GOVERNOR_STATE"] = "/nonexistent/claude-governor-state.json"
# the governor also reads the quota guard's state (bin/claude-quota-guard): a test never sees the real one
os.environ["CLAUDE_QUOTA_GUARD_STATE"] = "/nonexistent/claude-quota-guard-state.json"
# the gate profile (bin/ade_gates.py, bin/gate-profile, 2026-10-26) loosens both gates' numbers while it is active: a test never reads the
# operator's real profile, writes the real audit log, pings, or recomputes the real governor and guard. Pinned to missing paths
# unconditionally; tests/test_gates.py points them at fixtures per test.
for _var in ("GATE_PROFILE_STATE", "GATE_PROFILE_LOG", "GATE_PROFILE_PING", "GATE_PROFILE_GOVERNOR", "GATE_PROFILE_GUARD"):
    os.environ[_var] = f"/nonexistent/{_var.lower()}"
# fleet.LINKS_FILE (who has messaged whom, and who ever acked; the old relay.py wrote it, fleet.py list reads it, 2026-10-25): never the
# operator's real ledger. Unconditional. (The old relay.py's RELAY_DEFER_DIR queue went with it, 2026-11-06, docs/slim E3; this goes with
# fleet.py in E3b.)
_DEFER_ROOT = Path(tempfile.mkdtemp(prefix="relay-suite-links-"))
atexit.register(shutil.rmtree, _DEFER_ROOT, ignore_errors=True)
os.environ["RELAY_LINKS_FILE"] = str(_DEFER_ROOT / "relay" / "links.json")
# `load-watch admit --wait` and acp-dispatch-wait register their own deadline unless DEADLINE_NAME is set (2026-11-02, bin/deadline_wait.py).
# An existing test that runs one of them must neither write the real ~/.local/state/deadlines nor see an extra supervising process: a SET (empty)
# DEADLINE_NAME is the documented "already under a deadline" signal. test_deadline_wrappers.py unsets it per test, with its own state dir.
os.environ["DEADLINE_NAME"] = ""


# Pi/OMP/OpenCode identity markers steer bin/self-slash and autorename.py (2026-11-03). A suite run from inside such a
# session must behave as on CI: scrub them, and give every test its own autorename state root, never ~/.local/state.
_IDENTITY_VARS = ("PI_SESSION_ID", "PI_SESSION_FILE", "PI_PROVIDER", "PI_MODEL", "PI_REASONING_LEVEL", "PI_CODING_AGENT",
                  "AI_AGENT", "OMPCODE", "ADE_OPENCODE_SESSION_ID", "ADE_OPENCODE_DIRECTORY", "OPENCODE_SESSION_ID")


@pytest.fixture(autouse=True)
def _scrub_agent_identity(monkeypatch, tmp_path_factory):
    for var in _IDENTITY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AUTORENAME_STATE_DIR", str(tmp_path_factory.mktemp("autorename-state")))


@pytest.fixture(autouse=True)
def _fresh_relay_links():
    """No test inherits another's first-contact state: relay.py's footer and the link ledger depend on it (2026-10-25)."""
    Path(os.environ["RELAY_LINKS_FILE"]).unlink(missing_ok=True)
    yield
