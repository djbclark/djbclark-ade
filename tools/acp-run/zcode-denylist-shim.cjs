#!/usr/bin/env node
// zcode backend shim for acp-run --perm read-only / deny (2026-10-24).
//
// Why: `zcode app-server --stdio` (what zcode-acp-server spawns) ignores its own
// `--disallowed-tools` flag, and zcode-acp-server's session/create carries no `toolDenylist`
// (checked against zcode-app-cli vendor/zcode.cjs and zcode-acp-server dist/handlers/session.js:
// the flag and the ZCODE_DISALLOWED_TOOLS env that feeds it only reach the one-shot prompt/TUI
// path). A live probe showed the model still offered Bash, Edit, Write and the default-denied
// Cron* tools. The backend's own session/create, session/resume and session/send schemas do
// accept `toolDenylist` (removes whole tools from the registry), so this shim sits between
// zcode-acp-server and the real backend and adds it to those three requests.
//
// Used as ZCODE_BIN (acp-run puts a copy of the path under a per-run temp dir next to a `provider`
// link so zcode-acp-server still injects the builtin provider tables). Environment:
//   ZCODE_ACP_RUN_REAL_BIN   the real vendor/zcode.cjs (required)
//   ZCODE_DISALLOWED_TOOLS   tool names to remove, separated by spaces or commas (required; the
//                            same variable zcode-acp-server reads for the one-shot path)
//   ZCODE_ACP_RUN_ALLOWLIST  optional: keep ONLY these tools (toolAllowlist), which also drops
//                            every MCP tool and any tool a later zcode release adds
// Everything else (argv, stdout, stderr, exit code, signals) passes through unchanged.
"use strict";
const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");

const INJECT_METHODS = new Set(["session/create", "session/resume", "session/send"]);

function parseList(raw) {
  return [...new Set(String(raw || "").split(/[\s,]+/).filter(Boolean))];
}

// One stdin line (a JSON-RPC frame) -> the line to forward. Frames that are not one of the
// INJECT_METHODS, or are not JSON objects, are forwarded byte for byte.
function rewriteLine(line, deny, allow = []) {
  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    return line;
  }
  if (!msg || typeof msg !== "object" || !INJECT_METHODS.has(msg.method)) return line;
  const params = msg.params && typeof msg.params === "object" && !Array.isArray(msg.params) ? msg.params : {};
  const have = Array.isArray(params.toolDenylist) ? params.toolDenylist : [];
  msg.params = { ...params, toolDenylist: [...new Set([...have, ...deny])] };
  // session/send's strict schema has no toolAllowlist; the session's own was set at create/resume
  if (allow.length > 0 && msg.method !== "session/send") msg.params.toolAllowlist = allow;
  return JSON.stringify(msg);
}

function main() {
  const real = process.env.ZCODE_ACP_RUN_REAL_BIN;
  const deny = parseList(process.env.ZCODE_DISALLOWED_TOOLS);
  const allow = parseList(process.env.ZCODE_ACP_RUN_ALLOWLIST);
  if (!real || deny.length === 0) {
    process.stderr.write("zcode-denylist-shim: ZCODE_ACP_RUN_REAL_BIN and ZCODE_DISALLOWED_TOOLS are required\n");
    process.exit(2);
  }
  const child = spawn(process.execPath, [...process.execArgv, real, ...process.argv.slice(2)], {
    stdio: ["pipe", "inherit", "inherit"],
  });
  child.on("error", (err) => {
    process.stderr.write(`zcode-denylist-shim: cannot start ${real}: ${err.message}\n`);
    process.exit(127);
  });
  child.on("exit", (code, signal) => process.exit(signal ? 128 + (require("node:os").constants.signals[signal] || 1) : code ?? 1));
  child.stdin.on("error", () => {});
  for (const sig of ["SIGTERM", "SIGINT", "SIGHUP"]) process.on(sig, () => child.kill(sig));
  const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
  rl.on("line", (line) => child.stdin.write(rewriteLine(line, deny, allow) + "\n"));
  rl.on("close", () => child.stdin.end());
}

if (require.main === module) main();
module.exports = { rewriteLine, parseList };
