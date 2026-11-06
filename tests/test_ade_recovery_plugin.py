"""ade-recovery plugin (issue 278): node unit tests plus the bin/paseo-checkpoint wrapper end to end."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/ade-recovery"
CHECKPOINT = ROOT / "bin/paseo-checkpoint"
MIN_NODE = (22, 18)


def _node():
    """Return the node path, or skip (fail on Linux CI) when node is missing or too old."""
    node = shutil.which("node")
    version = None
    if node:
        out = subprocess.run([node, "-p", "process.versions.node"], capture_output=True, text=True, timeout=30).stdout.strip()
        try:
            version = tuple(int(x) for x in out.split(".")[:2])
        except ValueError:
            version = None
    if node and version and version >= MIN_NODE:
        return node
    if os.environ.get("CI") and sys.platform.startswith("linux"):
        pytest.fail("Linux CI must provide node >= 22.18")
    pytest.skip("Requires node >= 22.18")


def _env(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "ADE_STATE_ROOT": str(tmp_path / "state"),
        "PASEO_HOME": str(tmp_path / "paseo"),
    }


def test_node_unit_tests(tmp_path):
    node = _node()
    tests = sorted(str(p) for p in (PLUGIN / "server").glob("*.test.ts"))
    assert tests, "no plugin tests found"
    out = tmp_path / "node-test.log"
    with out.open("w") as fh:
        result = subprocess.run(
            [node, "--disable-warning=ExperimentalWarning", "--test", *tests],
            cwd=PLUGIN, env=_env(tmp_path), stdout=fh, stderr=subprocess.STDOUT, timeout=600,
        )
    assert result.returncode == 0, out.read_text()


def test_paseo_checkpoint_show_json(tmp_path):
    node = _node()
    env = _env(tmp_path)
    state = tmp_path / "state"
    root = state / "ade/srv1/ade-recovery/recovery/v1"
    root.mkdir(parents=True, mode=0o700)
    builder = tmp_path / "build.mjs"
    builder.write_text(
        """
import { sealRecord } from %r;
import { hostIdentity } from %r;
import fs from 'node:fs';
const h = hostIdentity();
const me = { pid: 2000000000, start: '1' };
const rec = sealRecord({
  schema: 'ade.recovery.passive/v1', generation: 1, writtenAt: new Date().toISOString(),
  writer: { ...me, plugin: 'ade-recovery', pluginVersion: '0.1.0', daemon: me, host: h.host, bootId: h.bootId },
  serverId: 'srv1', paseoAgentId: 'agent-1', provider: 'claude', cwd: '/nonexistent',
  host: h.host, bootId: h.bootId, platform: h.platform, state: 'archived', archivedAt: '2026-11-01T00:00:00.000Z',
  turns: [], interruptions: [],
});
fs.writeFileSync(process.argv[2], JSON.stringify(rec), { mode: 0o600 });
""" % ((PLUGIN / "server/record.ts").as_uri(), (PLUGIN / "server/host-identity.ts").as_uri())
    )
    built = subprocess.run(
        [node, "--disable-warning=ExperimentalWarning", str(builder), str(root / "agent-1.json")],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert built.returncode == 0, built.stdout + built.stderr

    shown = subprocess.run(
        [str(CHECKPOINT), "show", "agent-1", "--json", "--no-live"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert shown.returncode == 2, shown.stdout + shown.stderr
    data = json.loads(shown.stdout)
    assert data["verdict"] == "do-not-resume"
    assert data["agentId"] == "agent-1"

    missing = subprocess.run(
        [str(CHECKPOINT), "show", "nobody", "--no-live"], env=env, capture_output=True, text=True, timeout=60,
    )
    assert missing.returncode == 3, missing.stdout + missing.stderr


def test_paseo_checkpoint_usage(tmp_path):
    _node()
    env = _env(tmp_path)
    helped = subprocess.run([str(CHECKPOINT), "--help"], env=env, capture_output=True, text=True, timeout=60)
    assert helped.returncode == 0, helped.stderr
    assert "usage: paseo-checkpoint" in helped.stdout
    bad = subprocess.run([str(CHECKPOINT), "frobnicate"], env=env, capture_output=True, text=True, timeout=60)
    assert bad.returncode == 64, bad.stdout + bad.stderr


def test_paseo_checkpoint_resolves_symlink(tmp_path):
    _node()
    link = tmp_path / "bin" / "pc"
    link.parent.mkdir()
    link.symlink_to(CHECKPOINT)
    nested = tmp_path / "bin" / "pc2"
    nested.symlink_to("pc")  # relative link to a link
    result = subprocess.run([str(nested), "--help"], env=_env(tmp_path), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage: paseo-checkpoint" in result.stdout


def test_paseo_checkpoint_is_posix_sh():
    text = CHECKPOINT.read_text()
    assert text.startswith("#!/bin/sh\n")
    assert "readlink -f" not in text
    assert os.access(CHECKPOINT, os.X_OK)
