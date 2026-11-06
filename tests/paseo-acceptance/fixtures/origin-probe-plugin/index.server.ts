// origin-probe (plan T11, probes d1-07b and d1-10). Logs the payload of the agent lifecycle hooks to $ORIGIN_LOG
// (default $TMPDIR/origin-probe.log), one JSON line each: { hook, at, payload }. env values are dropped (keys kept).
// Hook names and the server.addHook shape CONFIRMED 2026-11-02 against https://paseo.sh/docs/plugins/hooks.md (Paseo >= 0.14).
// It changes nothing: every waiting hook returns undefined. Install ONLY in an isolated test home.
// SDK-create trigger: when $ORIGIN_TRIGGER names an existing file holding {"provider","cwd","title"}, the plugin deletes
// it and calls paseo.agents.create(...) with the SDK handle taken from the first hook call (the probe's plugin-SDK create path).
import { appendFileSync, existsSync, readFileSync, unlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const HOOKS = [
  "agent.create.before",
  "agent.create.after",
  "agent.open.before",
  "agent.close.after",
  "agent.archive.after",
  "agent.turn.before",
  "agent.turn.after",
];

function scrub(value: unknown, depth = 0): unknown {
  if (depth > 6 || value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map((v) => scrub(v, depth + 1));
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    out[k] = k === "env" && v && typeof v === "object" ? { __keys: Object.keys(v as object) } : scrub(v, depth + 1);
  }
  return out;
}

export default function contribute(server: any) {
  const file = process.env.ORIGIN_LOG || join(tmpdir(), "origin-probe.log");
  const trigger = process.env.ORIGIN_TRIGGER || "";
  const note = (extra: Record<string, unknown>) => appendFileSync(file, JSON.stringify({ at: Date.now(), ...extra }) + "\n");
  let paseo: any = null;
  const removers: Array<() => void> = [];
  for (const hook of HOOKS) {
    const remove = server.addHook(hook, async (payload: unknown, context: any) => {
      if (context && context.paseo) paseo = context.paseo;
      appendFileSync(file, JSON.stringify({ hook, at: Date.now(), payload: scrub(payload) }) + "\n");
      return undefined;
    });
    if (typeof remove === "function") removers.push(remove);
  }
  const timer = trigger
    ? setInterval(() => {
        if (!paseo || !existsSync(trigger)) return;
        const spec = JSON.parse(readFileSync(trigger, "utf8"));
        unlinkSync(trigger);
        note({ sdkCreate: "start", spec: { ...spec } });
        paseo.agents
          .create({ config: { provider: spec.provider }, cwd: spec.cwd, title: spec.title, labels: spec.labels })
          .then((a: any) => note({ sdkCreate: "ok", id: a && a.id }))
          .catch((e: any) => note({ sdkCreate: "error", message: String((e && e.message) || e) }));
      }, 500)
    : null;
  return () => {
    if (timer) clearInterval(timer);
    for (const r of removers) r();
  };
}
