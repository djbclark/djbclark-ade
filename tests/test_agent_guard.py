"""bin/agent_guard.py, the per-agent identity policy (2026-11-03 omp audit, A1/A3); kept with the acp-dispatch shim.

Moved out of tests/test_acp_dispatch_identity.py (slim-down E6, 2026-11-06): the pure policy checks stay; the old
dispatch-through-acp-run cases went with `--acp-arg`, and the shim's own use of the policy (its launch argv pins
exactly the admitted model) is tested in tests/test_acp_dispatch.py."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import agent_guard  # noqa: E402

ACP_RUN = ROOT / "tools" / "acp-run" / "acp-run"
GUARDED = ("omp", "codex", "claude")
OMP = "anthropic/claude-sonnet-5-5"
REPLACEMENTS = (["--model", "x/y"], ["--model=x/y"], ["--mod", "x/y"], ["--mod=x/y"], ["--m", "x"], ["--model x/y"],
                ["--set", "model=x/y"], ["--set=model=x/y"], ["--set", "provider=x"], ["--set", "model"], ["--set"],
                ["--se", "effort=high"], ["--meta", "{}"], ["--meta={}"], ["--agent-arg", "--model"],
                ["--agent-arg=--model", "--agent-arg=x"], ["--agent-arg=--provider"], ["--agent-arg=--profile=x"],
                ["--agent-env", "ANTHROPIC_API_KEY=x"], ["--agent-env=ANTHROPIC_BASE_URL=http://x"],
                ["--agent-e", "A=b"], ["--agent", "x"], ["--auth", "oauth"], ["--auth=oauth"], ["--au", "x"])


def test_guard_boundaries_for_every_guarded_agent():
    for agent in GUARDED:
        for args in REPLACEMENTS:
            why = agent_guard.identity_override(agent, args)
            assert why and "pass-through" in why and why.startswith(f"{agent}:"), (agent, args)
        for args in ([], None, ["--tripwire-exempt-kinds=read,search"], ["--perm", "all"], ["--mode", "x"],
                     ["--resume", "abc"], ["--set", "effort=high"], ["--set=reasoning_effort=low"], ["-m"]):
            assert agent_guard.identity_override(agent, args) is None, (agent, args)
    assert agent_guard.identity_override("omp", ["x", "--model", "a", "--perm", "all"], True) is None
    assert agent_guard.identity_override("omp", ["--model", "a", "--model", "b"], True) is not None


def test_the_policy_table_covers_every_acp_run_agent():
    tree = ast.parse(ACP_RUN.read_text())
    table = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "AGENTS" for t in n.targets))
    names = {k.value for k in table.keys}
    assert names == set(agent_guard.AGENT_GUARDS), "a new acp-run agent needs a row in bin/agent_guard.py"
    assert {a for a, row in agent_guard.AGENT_GUARDS.items() if row.status == agent_guard.GUARDED} == set(GUARDED)
    for agent in GUARDED:
        row = agent_guard.policy(agent)
        assert row.gates and row.identity and row.pool == agent


def test_unreviewed_agents_keep_pass_through():
    for agent in ("grok", "hermes", "opencode", "never-heard-of-it"):
        assert agent_guard.policy(agent).status == agent_guard.UNREVIEWED
        assert all(agent_guard.identity_override(agent, args) is None for args in REPLACEMENTS)
        assert agent_guard.record_refusal({"agent": agent, "model": "m", "acp_arg": ["--model=x"],
                                           "cmd": f"acp-run {agent} --model m --model x"}) is None


def test_a_stored_command_must_carry_exactly_the_admitted_model():
    for agent in GUARDED:
        primary = f"acp-run {agent} --model {OMP} --perm all"
        assert agent_guard.record_refusal({"agent": agent, "model": OMP, "cmd": primary}) is None
        for rec in ({"cmd": f"{primary} --model=other/x"}, {"cmd": f"acp-run {agent} --model other/x"},
                    {"cmd": f"acp-run {agent} --perm all"}, {"cmd": primary, "acp_arg": ["--meta={}"]}):
            assert agent_guard.record_refusal({"agent": agent, "model": OMP, **rec}), (agent, rec)
