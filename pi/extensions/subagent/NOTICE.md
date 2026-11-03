# Provenance

`index.ts` and `agents.ts` are derived from the `subagent` extension example shipped with
Pi (`@earendil-works/pi-coding-agent`, `examples/extensions/subagent`; MIT, Copyright (c) 2025
Mario Zechner; see `LICENSE`). ADE changes: per-invocation `model` and `thinking`
(invocation > agent frontmatter > Pi default, independently), validation, `--model`/`--thinking`
passed to the child, and the effective values reported in tool output. `config.ts`,
`test-invocation.mjs` and the surrounding tests are ADE additions.
