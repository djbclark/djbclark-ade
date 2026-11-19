import { chmodSync, mkdirSync, mkdtempSync, readdirSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

// Synthetic sealed source fixture; this is business behavior, NOT native proof.
export function fixture(t, id) {
  const base = realpathSync(mkdtempSync(join(tmpdir(), "ade-semantic-")));
  const root = join(base, "snapshot");
  const pluginRoot = join(root, "plugins", id);
  const files = ["bin/ade_directory_operations.py", "bin/ade_claims.py", "bin/ade_ws_autoname.py", "bin/ade_ws_names.py",
    "bin/ade-git-guard", "libexec/agent-bin/git", "libexec/git-hooks/pre-push", "libexec/git-hooks/reference-transaction",
    `plugins/${id}/index.server.ts`];
  for (const file of files) { const path = join(root, file); mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, "synthetic"); }
  function modes(path, seal) {
    const entries = readdirSync(path, { withFileTypes: true });
    if (!seal) chmodSync(path, 0o700);
    for (const e of entries) e.isDirectory() ? modes(join(path, e.name), seal) : chmodSync(join(path, e.name), seal ? 0o400 : 0o600);
    if (seal) chmodSync(path, 0o500);
  }
  modes(root, true);
  const stateDir = join(base, "state"); mkdirSync(stateDir, { mode: 0o700 });
  const cwd = join(base, "workspace"); mkdirSync(join(cwd, ".git"), { recursive: true });
  const mode = (value) => writeFileSync(join(stateDir, "ade-claim.mode"), value, { mode: 0o600 });
  mode("enforce");
  t.after(() => { modes(root, false); rmSync(base, { recursive: true, force: true }); });
  return { root, pluginRoot, cwd, stateDir, mode };
}
