"""Permission-safe RTK entrypoints and managed-copy restoration; no model calls."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
UNSAFE = ROOT / "tests/fixtures/rtk-unsafe-managed.ts"
SAFE = ROOT / "opencode-plugins/rtk.ts"
KNOWN = "8e46510ecdc95d4268838e435d33752d179675a6005b8de2483c7355b5d7da44"


def test_entrypoints_never_rewrite_or_read_permission_requests():
    node = shutil.which("node")
    assert node, "Node is required to validate the RTK plugin"
    script = r'''
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const source = readFileSync(process.argv[1], "utf8");
const { default: plugin } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
assert.equal(plugin.id, "rtk");
for (const response of [[], [{id:"pending", permission:"shell", patterns:["git push*"]}],
                       {rules:[]}, null, "bad", [{action:"shell", effect:"deny"}],
                       [{action:"*", effect:"ask"}], new Error("unreadable")]) {
  let reads = 0;
  const hooks = [];
  const ctx = {
    permission: {list: async () => {reads++; if (response instanceof Error) throw response; return response;}},
    tool: {hook: (name, handler) => hooks.push([name, handler])},
    $: () => {throw new Error("must not execute a shell or RTK");}
  };
  const v1 = await plugin.server(ctx);
  await plugin.setup(ctx);
  const event = {tool:"shell", input:{command:"git push origin main"}};
  const output = {args:{command:"git push origin main"}};
  for (const [name, handler] of hooks) if (name === "execute.before") await handler(event);
  if (v1["tool.execute.before"]) await v1["tool.execute.before"]({tool:"bash"}, output);
  assert.equal(event.input.command, "git push origin main");
  assert.equal(output.args.command, "git push origin main");
  assert.deepEqual(hooks, []);
  assert.deepEqual(v1, {});
  assert.equal(reads, 0);
}
'''
    p = subprocess.run([node, "--input-type=module", "-e", script, str(SAFE)],
                       capture_output=True, text=True, timeout=20)
    assert p.returncode == 0, p.stdout + p.stderr


@pytest.fixture
def guard(tmp_path):
    home = tmp_path / "home"
    config = home / ".config/opencode"
    plugins = config / "plugins"
    plugins.mkdir(parents=True)
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    shutil.copyfile(SAFE, canonical / "rtk.ts")
    bins = tmp_path / "bin"
    bins.mkdir()
    for name in ["grep", "date", "head"]:
        target = shutil.which("g" + name) or shutil.which(name)
        assert target
        (bins / ("g" + name)).symlink_to(target)
    marker = tmp_path / "rtk-was-called"
    (bins / "rtk").write_text('#!/usr/bin/env python3\nfrom pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\nraise SystemExit(0)\n')
    (bins / "rtk").chmod(0o755)
    state = home / ".local/state/opencode-plugin-guard"
    state.mkdir(parents=True)
    for old in ["obsolete", "upstream-v2-rtk"]:
        (state / old).touch()
    env = {**os.environ, "HOME": str(home), "PATH": str(bins) + os.pathsep + os.environ["PATH"],
           "OPENCODE_CONFIG_DIR": str(config), "OPENCODE_PLUGIN_GUARD_CANONICAL": str(canonical)}

    def run(*args):
        p = subprocess.run(["bash", str(ROOT / "bin/opencode-plugin-guard"), *args],
                           env=env, text=True, capture_output=True, timeout=15)
        assert not marker.exists(), "a guard probe must not execute RTK"
        return p
    return plugins, run


def test_known_unsafe_copy_migrates_despite_stale_retirement_markers(guard):
    plugins, run = guard
    assert hashlib.sha256(UNSAFE.read_bytes()).hexdigest() == KNOWN
    live = plugins / "rtk.ts"
    shutil.copyfile(UNSAFE, live)
    before = live.read_bytes()
    p = run("--check")
    assert p.returncode == 1, p.stdout + p.stderr
    assert "known unsafe" in p.stdout
    assert live.read_bytes() == before
    p = run()
    assert p.returncode == 1, p.stdout + p.stderr
    assert live.read_bytes() == SAFE.read_bytes()
    assert run("--check").returncode == 0
    assert run().returncode == 0


@pytest.mark.parametrize("old", [None, "export const RtkOpenCodePlugin = async () => ({})\n"])
def test_missing_or_v1_installer_copy_restores_disabled_module(guard, old):
    plugins, run = guard
    live = plugins / "rtk.ts"
    if old is not None:
        live.write_text(old)
    p = run()
    assert p.returncode == 1, p.stdout + p.stderr
    assert live.read_bytes() == SAFE.read_bytes()
    assert run().returncode == 0


def test_unknown_v2_copy_is_preserved_and_flagged(guard):
    plugins, run = guard
    live = plugins / "rtk.ts"
    custom = 'export default { id: "rtk", setup() { /* custom */ } }\n'
    live.write_text(custom)
    for args in [("--check",), ()]:
        p = run(*args)
        assert p.returncode == 1, p.stdout + p.stderr
        assert "permission safety needs review" in p.stdout
        assert live.read_text() == custom


def test_migration_replaces_real_target_and_preserves_symlink(guard, tmp_path):
    plugins, run = guard
    target = tmp_path / "shared-rtk.ts"
    shutil.copyfile(UNSAFE, target)
    live = plugins / "rtk.ts"
    live.symlink_to(target)
    p = run()
    assert p.returncode == 1, p.stdout + p.stderr
    assert live.is_symlink()
    assert target.read_bytes() == SAFE.read_bytes()


@pytest.mark.parametrize("old", [None, "v1", "unsafe"])
def test_unsafe_canonical_copy_is_refused_without_writing(guard, old):
    plugins, run = guard
    canonical = plugins.parents[2].parent / "canonical/rtk.ts"
    assert canonical.exists()
    shutil.copyfile(UNSAFE, canonical)
    live = plugins / "rtk.ts"
    if old == "v1":
        live.write_text("export const plugin = async () => ({})\n")
    elif old == "unsafe":
        shutil.copyfile(UNSAFE, live)
    before = live.read_bytes() if live.exists() else None
    for args in [("--check",), ()]:
        p = run(*args)
        assert p.returncode == 1, p.stdout + p.stderr
        assert "canonical" in p.stdout and "known unsafe shim" in p.stdout
        assert "restored" not in p.stdout
        assert (live.read_bytes() if live.exists() else None) == before


def test_dangling_symlink_is_preserved_without_creating_destination(guard, tmp_path):
    plugins, run = guard
    target = tmp_path / "missing-parent/target.ts"
    live = plugins / "rtk.ts"
    live.symlink_to(target)
    p = run()
    assert p.returncode == 1, p.stdout + p.stderr
    assert "dangling or cyclic" in p.stdout
    assert live.is_symlink()
    assert not target.parent.exists()


@pytest.mark.parametrize("symlink", [False, True])
def test_directory_entry_is_preserved_without_dropping_temp_file(guard, tmp_path, symlink):
    plugins, run = guard
    live = plugins / "rtk.ts"
    destination = tmp_path / "directory" if symlink else live
    destination.mkdir()
    if symlink:
        live.symlink_to(destination, target_is_directory=True)
    p = run()
    assert p.returncode == 1, p.stdout + p.stderr
    assert "non-regular plugin entry" in p.stdout
    assert live.is_dir()
    assert live.is_symlink() == symlink
    assert list(destination.iterdir()) == []


BRIDGE_OLD = 'if (error?.status !== 401 && error?.cause?.code !== "ECONNREFUSED" && error?.code !== "ConnectionRefused")\n'
BRIDGE_NEW = ('if (error?.status !== 401 && error?.cause?.code !== "ECONNREFUSED" && '
              'error?.code !== "ECONNREFUSED" && error?.code !== "ConnectionRefused")\n')


@pytest.fixture
def bridge(guard):
    plugins, run = guard
    shutil.copyfile(SAFE, plugins / "rtk.ts")  # isolate the bridge step from rtk restoration
    live = plugins / "paseo-managed-bridge/server.js"
    live.parent.mkdir()
    return live, run


def test_bridge_patch_is_applied_once_and_check_is_read_only(bridge):
    live, run = bridge
    live.write_text("before\n" + BRIDGE_OLD + "after\n")
    p = run("--check")
    assert (p.returncode, live.read_text()) == (0, "before\n" + BRIDGE_OLD + "after\n")
    assert "not applied" in p.stdout
    p = run()
    assert p.returncode == 1, p.stdout + p.stderr
    assert live.read_text() == "before\n" + BRIDGE_NEW + "after\n"
    assert not list(live.parent.glob("*.new.*"))
    for args in [("--check",), ()]:
        p = run(*args)
        assert p.returncode == 0, p.stdout + p.stderr
        assert "patch present" in p.stdout


def test_bridge_patch_follows_symlink_and_keeps_mode(bridge, tmp_path):
    live, run = bridge
    target = tmp_path / "real-server.js"
    target.write_text(BRIDGE_OLD)
    target.chmod(0o640)
    live.symlink_to(target)
    assert run().returncode == 1
    assert live.is_symlink() and target.read_text() == BRIDGE_NEW
    assert (target.stat().st_mode & 0o777) == 0o640


@pytest.mark.parametrize("text", [None, "a different bridge build\n", BRIDGE_OLD + BRIDGE_OLD])
def test_bridge_unknown_shape_or_absent_is_left_alone(bridge, text):
    live, run = bridge
    if text is not None:
        live.write_text(text)
    for args in [("--check",), ()]:
        p = run(*args)
        assert p.returncode == 0, p.stdout + p.stderr
    assert (live.read_text() if text is not None else None) == text
