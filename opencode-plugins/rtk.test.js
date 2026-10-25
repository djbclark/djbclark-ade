import { test } from "node:test";
import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import plugin from "./rtk.ts";

// A fake `rtk` on PATH so the plugin does not disable itself; configs live in a scratch XDG dir.
function scratch(config) {
  const root = mkdtempSync(join(tmpdir(), "rtk-test-"));
  const bin = join(root, "bin");
  mkdirSync(bin);
  writeFileSync(join(bin, "rtk"), "#!/bin/sh\nexit 0\n");
  chmodSync(join(bin, "rtk"), 0o755);
  const xdg = join(root, "xdg");
  mkdirSync(join(xdg, "opencode"), { recursive: true });
  if (config !== undefined) writeFileSync(join(xdg, "opencode", "opencode.json"), config);
  const project = join(root, "project");
  mkdirSync(project);
  return { bin, xdg, project };
}

async function hooksRegistered(config, list) {
  const s = scratch(config);
  const saved = { PATH: process.env.PATH, XDG: process.env.XDG_CONFIG_HOME };
  process.env.PATH = `${s.bin}:${saved.PATH}`;
  process.env.XDG_CONFIG_HOME = s.xdg;
  const hooks = [];
  try {
    await plugin.setup({
      location: { directory: s.project },
      permission: { list: async () => list },
      tool: { hook: (name) => hooks.push(name) },
    });
  } finally {
    process.env.PATH = saved.PATH;
    if (saved.XDG === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = saved.XDG;
  }
  return hooks;
}

// ctx.permission.list() returns pending requests, never effective rules: an empty or request-shaped
// answer must not make a configured deny/ask rule look absent (PR 64 review, 2026-10-25).
test("configured permission rules block the rewrite whatever permission.list() returns", async () => {
  const config = JSON.stringify({ permissions: [{ effect: "deny", action: "shell", pattern: "git push*" }] });
  for (const list of [[], [{ id: "per_1", permission: "shell", patterns: ["git push*"] }], null]) {
    assert.deepEqual(await hooksRegistered(config, list), [], JSON.stringify(list));
  }
});

test("an unparsable config fails closed", async () => {
  assert.deepEqual(await hooksRegistered("{ // jsonc\n}", []), []);
});

test("no permission rules in config: the rewrite hook is registered", async () => {
  assert.deepEqual(await hooksRegistered("{}", []), ["execute.before"]);
});
