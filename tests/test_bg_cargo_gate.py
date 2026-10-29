"""Cargo admission regression: real hook, unchanged resources, no compiler/model."""
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_cargo_permission_gate():
    node = shutil.which("node")
    assert node, "Node is required for the native OpenCode plugin regression"
    source = ROOT / "opencode-plugins/bg-cargo-gate.js"
    script = r'''
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const text = readFileSync(process.argv[1], "utf8");
const {default: plugin, requiresBg} = await import("data:text/javascript;base64," + Buffer.from(text).toString("base64"));
const deny = [
  "cd ~/src/sudo-secretspec && cargo build -p sudo-secretspec-cli --release 2>&1",
  "cargo build", "cargo test -q", "cargo check", "cargo clippy", "cargo bench",
  "cargo +stable build --release", "/Users/me/.cargo/bin/cargo build --release",
  "'/path with spaces/cargo' build --release", "CARGO_BUILD_JOBS=1 cargo build",
  "env CARGO_BUILD_JOBS=1 cargo build", "nice -n 10 cargo build",
  "command cargo build", "rtk cargo build", "nohup cargo build &",
  "cargo --manifest-path Cargo.toml build", "cargo --config build.jobs=1 build",
  "cargo run -- --help", "bg cargo build", "bgb cargo build",
  "echo --help; cargo build", "bash -lc 'cargo build --release'",
  "~/ops/site-private/bin/bg cargo check; cargo build",
  "timeout 1800 cargo build --release", "gtimeout -k 5 600 cargo test",
  "sudo cargo build", "sudo -k -n cargo build", "sudo -u root cargo build",
  "caffeinate -i cargo build --release", "rustup run stable cargo build", "rustup run stable -- cargo build",
  "env -S 'cargo build --release'",
  "xargs cargo build", "cargo install ripgrep --version 14.1.0",
  "cargo install --version 0.1.0 sudo-secretspec-cli",
  "CARGO_TARGET_DIR=/tmp/t \\\n  cargo build --release", "cargo \\\n  build --release",
  "nice -n 10 \\\n  cargo build", "cargo nextest run", "cargo fix --allow-dirty", "cargo d",
  "cargo miri test", "cargo llvm-cov", "cargo package", "cargo publish",
  "grep -q x <<< y\ncargo build --release", 'echo "see <<EOF"\ncargo build',
  "echo $((1<<4))\ncargo build", "/tmp/bg cargo build",
  "if cargo build --release; then echo ok; fi", "if ! cargo test; then exit 1; fi",
  "while cargo test; do sleep 1; done", "until cargo build; do sleep 5; done",
  "if true; then :; elif cargo build; then :; fi",
  "rtk test cargo test", "rtk err cargo build --release", "rtk run cargo build", "rtk proxy cargo build",
  "xargs -d '\\n' cargo build", "xargs -a list cargo build", "xargs -J % cargo build %",
  "/usr/bin/time -o t.log cargo build", "exec -a x cargo build", "env -P /usr/bin cargo build",
  "(( n << shift ))\ncargo build", 'git commit -m "a\nsee <<EOF x"\ncargo build',
];
const allow = [
  "~/ops/site-private/bin/bg cargo build -p sudo-secretspec-cli --release",
  "/Users/me/ops/site-private/bin/bg cargo build --release",
  "cd repo && /Users/me/ops/site-private/bin/bg cargo test",
  "cargo --version", "cargo build --help", "cargo metadata", "cargo fmt",
  "cargo install --list", "echo 'cargo build --release'", 'printf "%s" "cargo build"',
  "cat <<'EOF'\ncargo build\nEOF", "# cargo build\necho done",
  "ssh builder cargo build --release", "command -v cargo",
  "$HOME/ops/site-private/bin/bg cargo build --release",
  '"$HOME/ops/site-private/bin/bg" cargo test', "${HOME}/ops/site-private/bin/bg cargo build",
  "timeout 600 ~/ops/site-private/bin/bg cargo build", "cat <<EOF\ncargo build\nEOF",
  "rtk cargo --version", "rtk test ~/ops/site-private/bin/bg cargo test",
  "cargo clippy --version", "cargo nextest --version", "cargo llvm-cov --version",
];
for (const cmd of deny) assert.equal(requiresBg(cmd), true, cmd);
for (const cmd of allow) assert.equal(requiresBg(cmd), false, cmd);
const hooks = []; let disposed = 0;
const context = {permission: {
  async hook(name, fn) {
    hooks.push([name, fn]);
    return {dispose() {disposed++;}};
  }
}};
const dispose = await plugin.setup(context);
  assert.equal(hooks[0][0], "evaluate");
  for (const effect of ["allow", "ask"]) {
    for (const cmd of deny) {
      const event={action:"shell",resources:[cmd],effect};
      hooks[0][1](event);
      assert.equal(event.effect,"deny",cmd);
      assert.deepEqual(event.resources,[cmd]);
      assert.match(event.message,/--release is not an exemption/);
    }
    for (const cmd of allow) {
      const event={action:"shell",resources:[cmd],effect};hooks[0][1](event);
      assert.equal(event.effect,effect,cmd);assert.deepEqual(event.resources,[cmd]);
    }
  }
  const read={action:"read",resources:["cargo build"],effect:"allow"};hooks[0][1](read);assert.equal(read.effect,"allow");
await dispose();assert.equal(disposed,1);
'''
    result = subprocess.run(
        [node, "--input-type=module", "-e", script, str(source)],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
