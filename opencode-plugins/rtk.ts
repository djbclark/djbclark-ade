// RTK OpenCode compatibility module — 2026-10-25.
// Automatic shell rewriting is disabled in both host entrypoints. The native
// execute.before hook precedes permission evaluation, and permission.list()
// lists pending requests, not the effective rules. Neither an empty request
// list nor a partial config scan proves rewriting preserves permission matches.
// Use explicit `rtk <command>` calls; the host sees that original command.
// Managed/restored by bin/opencode-plugin-guard. Re-enable only after a reviewed
// integration proves permission matching is preserved on the supported hosts.

const notice = "[rtk] automatic shell rewriting disabled for permission safety; use explicit rtk commands"

async function RtkOpenCodePlugin() {
  console.warn(notice)
  return {}
}

async function setup() {
  console.warn(notice)
}

export default { id: "rtk", server: RtkOpenCodePlugin, setup }
