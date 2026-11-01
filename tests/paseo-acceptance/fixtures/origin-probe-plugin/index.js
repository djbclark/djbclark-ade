// DRAFT origin-probe plugin (plan T11, probes d1-07b and d1-10). Logs the payload of every create/open hook
// to $ORIGIN_LOG as one JSON line each. UNVERIFIED: the plugin SDK entry shape and hook registration names.
// TODO: confirm against the Paseo plugins_hooks.md before use.
const fs = require("fs");

function log(hook, payload) {
  const line = JSON.stringify({ hook, at: Date.now(), payload });
  fs.appendFileSync(process.env.ORIGIN_LOG || "/tmp/origin-probe.log", line + "\n");
}

module.exports = function activate(api) {
  // UNVERIFIED method name: api.hooks.on / api.on / api.registerHook
  const on = (api.hooks && api.hooks.on) || api.on;
  for (const hook of ["agent.create.before", "agent.open.before"]) {
    on.call(api.hooks || api, hook, async (payload) => { log(hook, payload); return undefined; });
  }
};
