# Provenance

`index.ts` and `agents.ts` are derived from the `subagent` extension example shipped with
Pi (`@earendil-works/pi-coding-agent`, `examples/extensions/subagent`; MIT, Copyright (c) 2025
Mario Zechner; see `LICENSE`). ADE changes: per-invocation `model` and `thinking`
(invocation > agent frontmatter > Pi default, independently), validation, `--model`/`--thinking`
passed to the child, and the effective values reported in tool output. `config.ts`,
`test-invocation.mjs` and the surrounding tests are ADE additions.

Forked from the example as shipped in `@earendil-works/pi-coding-agent` 1.5.0
(`examples/extensions/subagent`, the copy installed at `~/.pi/agent/extensions/subagent` on
2026-11-03; no git revision is recorded for it). Intentionally NOT adopted from newer upstream
behavior: `dispatchDefaults` (children inheriting the parent's model and thinking; here an
unset field means Pi's own default) and skipping the project-agent consent prompt when
`ctx.isProjectTrusted()` (here an interactive session always prompts for project agents, showing each agent's tools, model and thinking; a headless session refuses them unless the operator sets `PI_SUBAGENT_ALLOW_PROJECT_AGENTS=1`; the former model-visible `confirmProjectAgents` parameter was removed).
