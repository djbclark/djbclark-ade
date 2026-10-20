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
