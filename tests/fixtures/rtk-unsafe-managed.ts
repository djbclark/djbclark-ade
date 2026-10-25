import type { Plugin } from "@opencode-ai/plugin"
import { spawnSync } from "node:child_process"
import { existsSync, readFileSync } from "node:fs"
import { homedir } from "node:os"
import { dirname, join, resolve } from "node:path"

// RTK OpenCode plugin — rewrites commands to use rtk for token savings.
// Requires: rtk >= 0.23.0 in PATH.
//
// This is a thin delegating plugin: all rewrite logic lives in `rtk rewrite`,
// which is the single source of truth (src/discover/registry.rs).
// To add or change rewrite rules, edit the Rust registry — not this file.
//
// OpenCode 2 changed the plugin module contract: the default export must be an
// object with an `id` plus an `effect` or `setup` function. The old shapes
// (a bare exported function, or `{ id, server }`) are rejected at load with
// "Plugin must export a default definition with an id and an effect or setup
// function". The v1 hook factory is kept as `server` for OpenCode 1.
//
// Permission safety (measured 2026-10-11 on OpenCode 2.0.26): the
// `execute.before` hook runs BEFORE OpenCode evaluates its permission rules. A
// plugin that rewrites the command therefore changes which rule matches, so a
// rewrite can move a command out from under a `deny`/`ask` rule. `rtk rewrite`
// does not judge OpenCode's rules; `rtk hook opencode` (added upstream in
// rtk-ai/rtk#4187, not in any release yet) does. Until that ships, this plugin
// FAILS CLOSED: if the effective OpenCode configuration declares any shell
// permission rules, it registers no rewrite at all and says so on stderr.
// Reproduced and documented in djbclark-ade/docs/opencode-plugin-v2.md.
//
// Managed by `rtk init -g --opencode`, which writes the upstream v1 template —
// so this file is patched locally. djbclark-ade/bin/opencode-plugin-guard
// restores the v2 shape after such a run.

function rtkAvailable(): boolean {
  try {
    return spawnSync("rtk", ["--version"], { stdio: "ignore" }).status === 0
  } catch {
    return false
  }
}

function rtkRewrite(command: string): string | null {
  try {
    const result = spawnSync("rtk", ["rewrite", command], { encoding: "utf8" })
    if (result.status !== 0) return null
    const rewritten = String(result.stdout ?? "").trim()
    return rewritten && rewritten !== command ? rewritten : null
  } catch {
    return null
  }
}

// --- permission-rule detection (fail closed) -------------------------------

function configDir(): string {
  const xdg = (process.env.XDG_CONFIG_HOME ?? "").trim()
  return xdg ? join(xdg, "opencode") : join(homedir(), ".config", "opencode")
}

// Preferred source: the host itself. OpenCode 2.0.26 exposes
// `ctx.permission` = { get, hook, list, reply }, so the *effective* rules
// (global + project + managed) can be read instead of re-parsing config.
// Only deny/ask rules matter: making a command no longer match an allow rule
// cannot widen anything.
// Returns true = rules present, false = none, null = cannot tell.
async function rulesFromContext(ctx: any): Promise<boolean | null> {
  try {
    if (typeof ctx?.permission?.list !== "function") return null
    const raw = await ctx.permission.list()
    const list = Array.isArray(raw) ? raw : Array.isArray(raw?.rules) ? raw.rules : null
    if (!list) return null
    return list.some((rule: any) => {
      const effect = String(rule?.effect ?? "").toLowerCase()
      const action = String(rule?.action ?? "").toLowerCase()
      return (effect === "deny" || effect === "ask") && (action === "shell" || action === "*" || action === "")
    })
  } catch {
    return true // an unreadable rule list is treated as rules present
  }
}


// Global config plus every project config OpenCode would merge, walking up from
// `base` to the filesystem root (OpenCode's own discovery order).
function configFiles(base: string): string[] {
  const names = ["opencode.json", "opencode.jsonc"]
  const found: string[] = []
  for (const name of names) {
    const globalFile = join(configDir(), name)
    if (existsSync(globalFile)) found.push(globalFile)
  }
  let dir = resolve(base)
  for (;;) {
    for (const name of names) {
      const direct = join(dir, name)
      if (existsSync(direct)) found.push(direct)
      const nested = join(dir, ".opencode", name)
      if (existsSync(nested)) found.push(nested)
    }
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return found
}

// Any declared rule means "do not rewrite": matching semantics are OpenCode's,
// and guessing them wrong is exactly how a deny/ask rule gets bypassed.
function declaresPermissionRules(base: string): boolean {
  for (const file of configFiles(base)) {
    let cfg: any
    try {
      cfg = JSON.parse(readFileSync(file, "utf8"))
    } catch {
      return true // unparsable (JSONC comments?) — fail closed
    }
    if (Array.isArray(cfg?.permissions) && cfg.permissions.length > 0) return true
    if (cfg?.permission && typeof cfg.permission === "object") return true // v1 shape
    const policies = cfg?.experimental?.policies
    if (Array.isArray(policies) && policies.some((p: any) => p?.action === "permission")) return true
  }
  return false
}

// --- OpenCode 1 entrypoint (kept as `server`) ------------------------------

const RtkOpenCodePlugin: Plugin = async ({ $ }) => {
  try {
    await $`which rtk`.quiet()
  } catch {
    console.warn("[rtk] rtk binary not found in PATH — plugin disabled")
    return {}
  }

  return {
    "tool.execute.before": async (input, output) => {
      const tool = String(input?.tool ?? "").toLowerCase()
      if (tool !== "bash" && tool !== "shell") return
      const args = output?.args
      if (!args || typeof args !== "object") return

      const command = (args as Record<string, unknown>).command
      if (typeof command !== "string" || !command) return

      const rewritten = rtkRewrite(command)
      if (rewritten) {
        ;(args as Record<string, unknown>).command = rewritten
      }
    },
  }
}

// --- OpenCode 2 entrypoint -------------------------------------------------

async function setup(ctx: any) {
  if (!rtkAvailable()) {
    console.warn("[rtk] rtk binary not found in PATH — plugin disabled")
    return
  }
  const base = ctx?.location?.directory ?? ctx?.directory ?? process.cwd()
  const fromHost = await rulesFromContext(ctx)
  const ruleBearing = fromHost === null ? declaresPermissionRules(String(base)) : fromHost
  if (ruleBearing) {
    console.warn(
      "[rtk] OpenCode has shell permission rules in effect; skipping command rewriting so a rewrite cannot bypass a deny/ask rule (see rtk-ai/rtk#4187)",
    )
    return
  }
  if (typeof ctx?.tool?.hook !== "function") return

  ctx.tool.hook("execute.before", async (event: any) => {
    const input = event?.input
    if (!input || typeof input !== "object") return
    const command = input.command
    if (typeof command !== "string" || !command) return
    const rewritten = rtkRewrite(command)
    if (rewritten) input.command = rewritten
  })
}

export default { id: "rtk", server: RtkOpenCodePlugin, setup }
