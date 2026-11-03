# Pi subagent extension (2026-11-03)

`pi/extensions/subagent/` is the ADE copy of Pi's `subagent` example extension (MIT, provenance in
its `NOTICE.md`). It delegates a task to a separate `pi` process using an agent profile from
`~/.pi/agent/agents/*.md` (user) or the nearest `.pi/agents/` (project; the consent prompt for
project agents is kept).

## Model and thinking effort

Each `subagent` call (single), each `tasks[]` item (parallel) and each `chain[]` step may set
`model` and `thinking` (`off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`). They resolve
independently, per child:

1. the invocation value;
2. the agent profile frontmatter (`model:`, `thinking:`), e.g. `frontier-astra` has
   `model: openai/gpt-6-astra:high`, `thinking: high`; `astra-worker` has the same model and thinking but a wider tool set (`read, bash, edit, write` against `read, bash, write`, so it can edit files, not only write a report) and is restricted by its prompt to one claimed workspace;
3. Pi's own default (the flag is then omitted; the parent's model is not inherited).

The chosen values are passed as `--model` / `--thinking` and reported in the tool output
(`model=..., thinking=...`; `default` means Pi's default) and in `details.results[].selectedConfig`.
Model IDs are passed through untouched, so `provider/model`, nested namespaces
(`openai/gpt-6-astra`) and the `:high` suffix form work as Pi defines them; an explicit `thinking`
beats a suffix. A frontmatter `thinking` also beats a `:suffix` on an invocation `model`
(`{model: "x/y:low"}` with frontmatter `thinking: high` runs at high), so to change effort
for one call, pass the `thinking` parameter, not a suffix.

Invalid values (empty model, unknown effort) fail that child before any process starts. A
malformed frontmatter `model:`/`thinking:` fails the agent only for the field the invocation
does not set: an invocation `thinking` makes a bad frontmatter `thinking` irrelevant, and the
same for `model`. In chain mode every step's agent and configuration is checked first
("Chain not started: step N ..."), so a bad later step stops the chain before any earlier,
possibly write-capable, step runs. Top-level `model`/`thinking` with `tasks` or `chain` is rejected; put
them on each item. Example: `{agent: "frontier-astra", task: "...", thinking: "xhigh"}`.

## Install

The repo has no Pi extension installer yet (Pi skills already come through
`bin/skill-everywhere`, target `pi` = `~/.agents/skills`). Install by hand, replacing the stock
example, then reload Pi:

```sh
rm -rf ~/.pi/agent/extensions/subagent        # or move the stock example aside
ln -s "$PWD/pi/extensions/subagent" ~/.pi/agent/extensions/subagent
```

Pi resolves its own packages for extensions; `npm install` in the directory is only needed for
the tests. Profiles stay in `~/.pi/agent/agents/` and are not managed by this repo.

## Tests

`tests/test_pi_subagent_invocation.py` runs `pi/extensions/subagent/test-invocation.mjs`
(fake child processes, no network, no real Pi). It needs `npm ci` in the extension directory
(done in the Linux CI job); it skips locally when dependencies are absent.
