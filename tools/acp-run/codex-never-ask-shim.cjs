#!/usr/bin/env node
// codex app-server shim for acp-run --perm read-only (2026-11-02).
//
// Why: codex-acp's "read-only" session mode is the preset {approvalPolicy "on-request", sandbox
// readOnly}, and codex-acp sends that approvalPolicy with EVERY turn/start (dist/index.js
// `sendPrompt`), so no CODEX_CONFIG approval_policy can override it (probed: a read-only run with
// CODEX_CONFIG={"approval_policy":"never"} still got the permission request). Under on-request a
// command the sandbox blocks (no network, no writes) comes back as an approval request whose only
// reject option is codex's `cancel` decision, and codex ends the WHOLE TURN on it (stopReason
// "cancelled", no report): a read-only review that tried one `gh run view` died after 113 s
// (tendcf v5-s1, 2026-11-02). With approvalPolicy "never" the same blocked command is returned to
// the model as a failed command and the turn goes on; the sandbox itself is unchanged.
//
// So this shim sits between codex-acp and the real `codex app-server` (acp-run starts it as
// CODEX_PATH) and sets approvalPolicy to "never" in every request that carries one, and in the four
// requests that create or run a thread (thread/start, thread/resume, thread/fork, turn/start) even
// when it does not. It never touches the sandbox, so it can only make codex ask LESS.
// Environment:
//   ACP_RUN_REAL_CODEX   the real codex entry: a .js file (run with this node) or an executable
//                        (required)
// Everything else (argv, stdout, stderr, exit code, signals) passes through unchanged.
"use strict";
const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");

const ALWAYS_METHODS = new Set(["thread/start", "thread/resume", "thread/fork", "turn/start"]);

// One stdin line (a JSON-RPC frame) -> the line to forward. Frames that are not JSON objects with a
// params object are forwarded byte for byte.
function rewriteLine(line) {
  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    return line;
  }
  if (!msg || typeof msg !== "object" || typeof msg.method !== "string") return line;
  const params = msg.params;
  if (!params || typeof params !== "object" || Array.isArray(params)) return line;
  let changed = false;
  if (ALWAYS_METHODS.has(msg.method) || Object.prototype.hasOwnProperty.call(params, "approvalPolicy")) {
    if (params.approvalPolicy !== "never") {
      params.approvalPolicy = "never";
      changed = true;
    }
  }
  const cfg = params.config;
  if (cfg && typeof cfg === "object" && !Array.isArray(cfg) &&
      Object.prototype.hasOwnProperty.call(cfg, "approval_policy") && cfg.approval_policy !== "never") {
    cfg.approval_policy = "never";
    changed = true;
  }
  return changed ? JSON.stringify(msg) : line;
}

function main() {
  const real = process.env.ACP_RUN_REAL_CODEX;
  if (!real) {
    process.stderr.write("codex-never-ask-shim: ACP_RUN_REAL_CODEX is required\n");
    process.exit(2);
  }
  const argv = process.argv.slice(2);
  const child = real.endsWith(".js") || real.endsWith(".cjs") || real.endsWith(".mjs")
    ? spawn(process.execPath, [...process.execArgv, real, ...argv], { stdio: ["pipe", "inherit", "inherit"] })
    : spawn(real, argv, { stdio: ["pipe", "inherit", "inherit"] });
  child.on("error", (err) => {
    process.stderr.write(`codex-never-ask-shim: cannot start ${real}: ${err.message}\n`);
    process.exit(127);
  });
  child.on("exit", (code, signal) => process.exit(signal ? 128 + (require("node:os").constants.signals[signal] || 1) : code ?? 1));
  child.stdin.on("error", () => {});
  for (const sig of ["SIGTERM", "SIGINT", "SIGHUP"]) process.on(sig, () => child.kill(sig));
  const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
  rl.on("line", (line) => child.stdin.write(rewriteLine(line) + "\n"));
  rl.on("close", () => child.stdin.end());
}

if (require.main === module) main();
module.exports = { rewriteLine };
