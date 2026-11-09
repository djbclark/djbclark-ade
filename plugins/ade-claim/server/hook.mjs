import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  buildAdeClaimsNewArgv,
  parseWorktreePayload,
  resolveAdeClaimsScript,
} from "./claim-lib.mjs";

/** Reviewed plugin directory (never the agent's worktree). */
const PLUGIN_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

/** @param {string} cwd */
export function gitRevParseHead(cwd) {
  const r = spawnSync("git", ["-C", cwd, "rev-parse", "HEAD"], { encoding: "utf8" });
  if (r.status !== 0 || !r.stdout?.trim()) {
    throw new Error(`git rev-parse HEAD failed in ${cwd}: ${r.stderr?.trim() || r.status}`);
  }
  return r.stdout.trim();
}

/** @param {string} cwd */
export function gitRemoteOriginUrl(cwd) {
  const r = spawnSync(
    "git",
    ["-C", cwd, "config", "--get", "remote.origin.url"],
    { encoding: "utf8" },
  );
  if (r.status !== 0) return "";
  return (r.stdout || "").trim();
}

/**
 * @param {{ addHook: (name: string, handler: (ctx: { worktree: unknown }) => Promise<void>) => () => void }} server
 */
export function registerWorktreeClaimHook(server) {
  return server.addHook("worktree.create.after", async ({ worktree }) => {
    const wt = parseWorktreePayload(worktree);
    const script = resolveAdeClaimsScript(wt, process.env, { pluginRoot: PLUGIN_ROOT });
    const baseSha = gitRevParseHead(wt.path);
    const repoOrigin = gitRemoteOriginUrl(wt.path);
    const { python, argv } = buildAdeClaimsNewArgv(wt, {
      adeClaimsScript: script,
      baseSha,
      repoOrigin,
    });
    const run = spawnSync(python, [script, ...argv], { encoding: "utf8" });
    if (run.status !== 0) {
      const detail = (run.stderr || run.stdout || "").trim();
      throw new Error(`ade_claims.py new failed (exit ${run.status})${detail ? `: ${detail}` : ""}`);
    }
  });
}
