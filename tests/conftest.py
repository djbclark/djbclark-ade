"""Shared pytest setup for the djbclark-ade tests."""
import os

# acp-dispatch holds a slice's start while the real machine is overloaded
# (bin/acp-dispatch wait_for_capacity). Tests must not depend on the host's
# load: with it on, a busy machine made dispatch tests wait and fail
# (2026-10-12). test_acp_dispatch_gate.py exercises the gate directly.
os.environ.setdefault("ACP_DISPATCH_NO_GATE", "1")
# A quota stop schedules an in-place resume with `launchctl submit` (2026-10-18). No test may
# leave a real launchd job behind: test_acp_dispatch.py gives finalize a fake launchctl that
# records its arguments; anything else gets a no-op.
os.environ.setdefault("ACP_DISPATCH_LAUNCHCTL", "/usr/bin/true")
