"""Shared pytest setup for the djbclark-ade tests."""
import os
import tempfile
from pathlib import Path

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
# `reap` throttles dir sweeps younger than 60 s through a machine-wide stamp (2026-10-18).
# Off in tests: dir sweeps must always run and must never touch the real machine's stamp;
# test_acp_dispatch_waiter.py turns the throttle on explicitly per test.
os.environ.setdefault("ACP_DISPATCH_REAP_MIN_INTERVAL", "0")
# route_agent.load_snapshot() runs `aiuse --available --json` unless a snapshot is pinned (2026-10-20).
# Off in tests so the suite never depends on, or spawns, the host's real aiuse;
# test_route_agent.py's TestQuotaFromAiuseAvailable turns it on per test.
os.environ.setdefault("ROUTE_AGENT_AIUSE", "off")
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
# relay.py reads RELAY_DEFER_DIR once, at import: every test module that loads it (test_relay_*.py, test_session_relay.py)
# gets a throwaway queue directory, so no test reads, sweeps, expires or prunes the operator's real deferred-send queue
# ~/.local/state/relay/deferred (2026-10-24: test_session_relay.py ran relay.main(), whose opportunistic sweep expired and
# pruned real records and started real deliverers). Unconditional: an outer value must not point the suite at a real queue.
# tests/test_zz_relay_real_state_untouched.py compares the real directory with this snapshot at the end of the suite.
REAL_RELAY_DIR = Path.home() / ".local/state/relay"


def relay_state_snapshot(root: Path = REAL_RELAY_DIR) -> dict[str, tuple[int, int]] | None:
    """{relative path: (mtime_ns, size)} of everything under ROOT, its directories included; None when ROOT is absent."""
    if not root.exists():
        return None
    snap = {".": (root.stat().st_mtime_ns, 0)}
    for p in sorted(root.rglob("*")):
        st = p.lstat()
        snap[str(p.relative_to(root))] = (st.st_mtime_ns, st.st_size)
    return snap


REAL_RELAY_BEFORE = relay_state_snapshot()
os.environ["RELAY_DEFER_DIR"] = str(Path(tempfile.mkdtemp(prefix="relay-suite-defer-")) / "relay" / "deferred")
