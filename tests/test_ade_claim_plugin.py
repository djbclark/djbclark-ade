"""Unit tests for plugins/ade-claim (no live Paseo daemon)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADE_CLAIMS = ROOT / "bin" / "ade_claims.py"


PLUGIN_SERVER = ROOT / "plugins" / "ade-claim" / "server"

# Ambient values that would change what the node tests observe (the daemon env is the plugin's input).
_PLUGIN_ENV_KEYS = (
    "ADE_CLAIM_DRY_RUN", "ADE_CLAIM_TTL", "ADE_CLAIMS_PY", "ADE_GIT_GUARD", "ADE_AGENT_BIN", "ADE_STATE_DIR",
)


def _clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _PLUGIN_ENV_KEYS}
    env.update(extra)
    return env


def test_ade_claim_plugin_argv_builder() -> None:
    """claim-lib.test.mjs: argv builders, observe predicate, mode file, JSONL log, all four hooks x both modes."""
    node = shutil.which("node")
    assert node, "Node is required to validate the ade-claim Paseo plugin"
    test_file = PLUGIN_SERVER / "claim-lib.test.mjs"
    result = subprocess.run(
        [node, "--test", str(test_file)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=_clean_env(),
    )
    assert result.returncode == 0, result.stdout + result.stderr


_DRIVER = r"""
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { registerAdeClaimHooks } from %(hook)s;

const [, , worktree, stateDir, mode] = process.argv;
if (mode !== "none") writeFileSync(join(stateDir, "ade-claim.mode"), mode + "\n");
const hooks = new Map();
registerAdeClaimHooks({ addHook: (n, f) => { hooks.set(n, f); return () => {}; } }, { stateDir, log: () => {} });
await hooks.get("worktree.create.after")({ worktree: { path: worktree, branch: "obs/e2e", sourceCheckout: worktree } });
await hooks.get("agent.create.after")({ agent: { id: "agent-e2e", cwd: worktree } });
const out = await hooks.get("agent.open.before")({ request: { agentId: "agent-e2e", cwd: worktree, env: {} } });
await hooks.get("workspace.archive.after")({ workspace: { id: "ws-e2e", cwd: worktree } });
console.log(JSON.stringify({ openChanged: out !== undefined, env: out?.env ?? null }));
"""


def _run_driver(tmp_path: Path, mode: str) -> tuple[dict, Path, Path]:
    """Drive the real hooks against the real ade_claims.py + git in a throwaway home (no daemon)."""
    node = shutil.which("node")
    assert node, "Node is required to validate the ade-claim Paseo plugin"
    home = tmp_path / "home"
    state = home / ".local" / "state" / "djbclark-ade"
    state.mkdir(parents=True)
    state.chmod(0o700)
    ade_state = tmp_path / "ade-state"
    ade_state.mkdir()
    agent_bin = tmp_path / "agent-bin"
    agent_bin.mkdir()
    (agent_bin / "git").write_text("#!/bin/sh\n")
    guard = tmp_path / "guard-ran"
    guard_script = tmp_path / "ade-git-guard"
    guard_script.write_text(f"#!/bin/sh\necho \"$@\" >> {guard}\n")
    guard_script.chmod(0o755)
    wt = tmp_path / "wt"
    subprocess.run(["git", "init", "-q", str(wt)], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
    )
    driver = tmp_path / "driver.mjs"
    driver.write_text(_DRIVER % {"hook": json.dumps((PLUGIN_SERVER / "hook.mjs").as_uri())})
    # The plugin finds its state dir via the password database (never $HOME), so the driver passes it in.
    env = _clean_env(
        ADE_CLAIMS_PY=str(ADE_CLAIMS), ADE_GIT_GUARD=str(guard_script), ADE_AGENT_BIN=str(agent_bin),
        ADE_STATE_DIR=str(ade_state),
    )
    result = subprocess.run(
        [node, str(driver), str(wt), str(state), mode],
        capture_output=True, text=True, timeout=60, check=False, env=env, cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1]), ade_state, guard


def _claim_files(ade_state: Path) -> list[Path]:
    claims = ade_state / "claims"
    return sorted(claims.glob("*.json")) if claims.is_dir() else []


@pytest.mark.parametrize("mode", ["none", "observe"])
def test_hooks_observe_writes_nothing_real_registry(tmp_path: Path, mode: str) -> None:
    """Real ade_claims.py + git: a missing mode file or `observe` leaves registry, guard and env untouched."""
    out, ade_state, guard = _run_driver(tmp_path, mode)
    assert _claim_files(ade_state) == []
    assert not guard.exists(), "ade-git-guard install must not run in observe"
    assert out == {"openChanged": False, "env": None}
    log = tmp_path / "home" / ".local" / "state" / "djbclark-ade" / "ade-claim-observe.jsonl"
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert [r["hook"] for r in rows] == [
        "worktree.create.after", "agent.create.after", "agent.open.before", "workspace.archive.after",
    ]
    assert {r["mode"] for r in rows} == {"observe"}
    assert rows[0]["planned"]["argv"][2] == "new"


def test_hooks_enforce_acts_on_real_registry(tmp_path: Path) -> None:
    """Same driver with `enforce`: claim created, owner bound, env exported, guard run, claim released."""
    out, ade_state, guard = _run_driver(tmp_path, "enforce")
    files = _claim_files(ade_state)
    assert len(files) == 1
    claim = json.loads(files[0].read_text())
    assert claim["owner"]["agent"] == "agent-e2e"
    assert claim["state"] == "released"
    assert guard.read_text().startswith("install ")
    assert out["openChanged"] is True
    assert out["env"]["ADE_CLAIM_ID"] == claim["id"]
    assert out["env"]["PATH"].split(":")[0].endswith("agent-bin")


def test_bind_owner_merges_owner_on_active_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """W3 CLI: ade_claims.py bind-owner stamps owner.agent / owner.record."""
    state = tmp_path / "ade-state"
    state.mkdir()
    monkeypatch.setenv("ADE_STATE_DIR", str(state))
    # Isolate from a real git worktree: --no-pointer.
    repo = tmp_path / "ws"
    repo.mkdir()
    new = subprocess.run(
        [
            sys.executable,
            str(ADE_CLAIMS),
            "new",
            "--id",
            "wt-w3-test",
            "--path",
            str(repo),
            "--branch",
            "cursor/w3",
            "--base-sha",
            "deadbeef",
            "--no-pointer",
            "--ttl",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ADE_STATE_DIR": str(state)},
    )
    assert new.returncode == 0, new.stdout + new.stderr

    bind = subprocess.run(
        [
            sys.executable,
            str(ADE_CLAIMS),
            "bind-owner",
            "--id",
            "wt-w3-test",
            "--owner-agent",
            "agent-abc",
            "--owner-record",
            "agent-abc",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ADE_STATE_DIR": str(state)},
    )
    assert bind.returncode == 0, bind.stdout + bind.stderr
    assert bind.stdout.strip() == "wt-w3-test"

    listed = subprocess.run(
        [sys.executable, str(ADE_CLAIMS), "list", "--json", "--state", "active"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ADE_STATE_DIR": str(state)},
    )
    assert listed.returncode == 0, listed.stdout + listed.stderr
    rows = json.loads(listed.stdout)
    hit = next(r for r in rows if r["id"] == "wt-w3-test")
    assert hit["owner"]["agent"] == "agent-abc"
    assert hit["owner"]["record"] == "agent-abc"


def test_bind_owner_refuses_missing_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "ade-state"
    state.mkdir()
    monkeypatch.setenv("ADE_STATE_DIR", str(state))
    missing = subprocess.run(
        [
            sys.executable,
            str(ADE_CLAIMS),
            "bind-owner",
            "--id",
            "no-such",
            "--owner-agent",
            "agent-x",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ADE_STATE_DIR": str(state)},
    )
    assert missing.returncode == 2
    assert "no claim" in missing.stderr
