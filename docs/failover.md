# failover — one chain library for every tool that must not stop on one dead pool

`bin/failover.py` (2026-10-12) runs a task through an ordered chain of agent
routes and stops at the first that works. `bin/skillopt-night` is its first
consumer ([skillopt-sleep.md](skillopt-sleep.md) section 4). It is built so
`acp-dispatch`, bigteam and other bin tools can import it later.

## Pieces

1. **Registry** (`REGISTRY`): one `Tui` per route, with its kind (`acp` through
   acp-run, or `openai_compat`), acp agent id, vendor, aiuse pool and family
   (agy and opencode map the pool from the model prefix; opencode `sipb/` has
   none), known model ids, a model allow-regex (claude: Haiku or Sonnet only),
   the effort lever (`set:effort` for claude, `set:thought` for zcode, `suffix`
   for agy, none for opencode, crush and hermes), the native model id (claude
   `haiku` is `claude-haiku-5-5`), health URLs, probe, endpoint and secret name
   (the direct SIPB route). `hermes` (2026-10-13) is `hermes acp`: no `--model`
   (Hermes picks its own: `~/.hermes/config.yaml` `model.default` with its
   free-first `fallback_providers`, which can reach paid routes), no aiuse pool,
   so like crush it gets the one-prompt probe.
2. **Policy at load time** (`load_chain`): the global `DENY` list (cursor,
   cline/ClinePass, opus, fable; operator 2026-10-12; hermes was on it until the
   operator admitted it on 2026-10-13), plus any words the
   caller adds (skillopt-night adds muse, pi, grok, codex, copilot), is matched
   as whole tokens of tui, model and label (so `pi` never catches `api`); a caller allowlist; unknown TUIs; models a TUI refuses;
   efforts with no lever; a `perm` other than `deny` or `all` (item 9). A
   violation refuses the whole chain (`ChainError`).
3. **Preflight** (`preflight`): the agent has an `ok` row in `acp-run --list`
   (route_agent's reader), the pool is `usable_now` in `aiuse --available --json`
   with headroom above the entry's `floor_percent`, the secret is declared in
   sudo-secretspec (value-free `schema`), the endpoint accepts a TCP connection,
   a health URL (opencode's `sipb/` models: the proxy's `/api/version`) answers
   200. Routes with no quota pool to read (crush, hermes) get a one-prompt
   probe; it and the deny canary (item 7) are the only preflight steps that call
   a model; `check --probe` runs them, plain `check` reports them as not run.
   A `perm: all` entry has no canary (item 9), so plain `check` spends nothing
   on it and `check --probe` spends only the probe of entries marked probe.

   **Cached for an hour (2026-10-13).** `run_chain` calls `preflight_cached`,
   which keeps each result, ok or refused, per (tui, model, effort, pool,
   floor, and perm when it is not `deny`) for `PREFLIGHT_TTL_S` (3600 s) and logs a hit as `preflight cached
   (Ns old): <why>`. Before, skillopt-night ran preflight again for each of its
   eight sources. An expired entry drops the aiuse reading and its own canary
   and probe, so the recheck is real. `check` and `check --probe` (and
   skillopt-night `chain-check`) never use the cache.
4. **Ordered attempts** (`run_chain`): preflight, then the caller's function;
   `AttemptFailed` moves on. Every step is one line in the attempt log
   (`~/.local/state/failover/attempts.jsonl`, or the caller's path), ending in
   `chain_exhausted` when nothing worked. Prompt retries add `"phase": "retry"`
   lines (item 8).
5. **Executors**: `ask(entry, prompt)` answers one prompt in a fresh context
   (acp-run in an empty temp dir with the entry's `--perm`, `deny` unless the
   chain says otherwise (item 9), prompt from a 0600 file, never argv; acp-run's
   `claude -p` fallback also reads stdin since 2026-10-12). Under `deny` tools
   stay off because acp-run enforces deny per agent and its tripwire exits 77
   when a tool still runs without asking, which `ask` turns into
   `AttemptFailed`; the canary checks it before use. Under `all` the agent runs
   any tool it wants and nothing checks it. Or an
   OpenAI-compatible POST with the key read once per process by
   `sudo-secretspec get`, sent only to the registry endpoint, https or
   loopback, and never across a redirect; `ask_many` answers a batch on one entry and fails the
   batch on the first failure that is not a retried startup failure (item 8); `run_command(entry, argv)` runs any command with
   `{tui} {agent} {model} {effort} {endpoint}` replaced in argv, `FAILOVER_*`
   exported, and the entry's secret exported only into that child. Every child
   gets a minimal env (`BASE_ENV_KEYS` plus the entry's allow-listed `env`) and
   runs in its own process group, killed whole on timeout. acp-run logs go to
   `~/.local/state/failover/acp-logs/` (0700), trimmed by `sweep_logs()`.
6. **Chain policy against config tampering** (2026-10-12): `extra_args` is an
   allow-list (`EXTRA_ARGS_ALLOWED`: `--prompt-retries`, `--handshake-tries`,
   `--handshake-timeout`, `--max-load`, `--load-wait`, `--no-fallback`, and
   `--set` only as `thought=` or `effort=` with low/medium/high/max), spelled
   exactly and value-checked; everything else is refused, abbreviations such as
   `--per all` or `-Call` included (acp-run also sets `allow_abbrev=False`).
   Every token and env value is checked against the deny list, and `env` keys
   outside `ENV_ALLOW` are refused.
7. **Canary**: each acp entry is asked to create a file and write a basic-memory
   note; it passes only with 0 tool calls (not merely denied), no file and no
   tripwire. The policy is per TUI in the registry (`Tui.canary`), so a chain
   file cannot loosen it: `strict` (default), `asked_denied_ok` (tool calls
   tolerated if every one asked permission and was denied), or `reads_ok`, set
   only on agy (djbclark, 2026-10-12): calls of a read-only ACP kind (`read`,
   `search`; agy's `view_file` is kind `read`, while its shell commands, even
   `cat` or `grep`, are kind `execute`) may run unasked, and every other call
   (execute, edit, delete, MCP/other, subagent) must ask and be denied. The same
   registry entry (`Tui.tripwire_exempt`) makes `ask()` pass
   `--tripwire-exempt-kinds read,search` to acp-run for agy only; acp-run accepts
   only read-only kinds there, and `extra_args` cannot add the flag. The file
   check applies to every policy.

   **crush is `strict`, with no exemption** (2026-10-13). The 03:43 canary that
   night tripped (exit 77): crush-acp asks before `bash` and `edit` but runs
   `glob`, `grep`, `ls`, `view` and its other read-only tools without asking.
   Since then acp-run gives crush no tools at all under `--perm deny`: every
   name on crush's tool allow list is in `options.disabled_tools` in two per-run
   config layers, plus the user-config strip (no MCP, LSP, hooks, global context
   or skills); see `tools/acp-run/README.md`. The real preflight for the chain
   entry `{"tui": "crush", "timeout": 1800}` (2026-10-13 11:35, through
   `failover.preflight`) passed: probe answered `OK`; canary held with rc 0,
   0 tool calls and no file (the model wrote its `touch` as a fake `<bash ...>`
   tag in plain text); 42 s for both. So crush answers night prompts as text
   only, like claude under deny.

   **Accepted risk (agy only):** an unasked read can pull a file's contents into
   an answer, and answers flow into reflection and into staged skill edits.
   `skillopt-night preadopt-check` flags commands, URLs and secret words but not
   leaked file content, so adoption review must read the diff for such content.
8. **Startup retries and the spawn gate** (2026-10-13). On the night of
   2026-10-13 all 21 failed skillopt-night attempts died before the model
   answered: opencode's `ServiceUnavailableError: Location plugins did not
   finish activating` and `OpenCode server is unavailable`, `session/new` and
   agy `initialize` handshake hangs. One such prompt failed its whole entry.
   `ask` now raises `StartupFailed`, a subclass of `AttemptFailed`, when
   acp-run's result record proves nothing ran: 0 turns, 0 tool calls, no
   permission request, no answer, and a failure class other than
   `NOT_RETRIED` (quota, plan, auth, refused, tripwire). Exit 75 from acp-run's
   `--max-load` counts too. No result record, or a record without `turns`, is
   not proof, so it is never retried. `ask_many(entry, prompts, jobs=,
   pacing=)` retries such a prompt up to `PROMPT_RETRIES` (2) more times after
   `RETRY_BACKOFF_S` (20 s, 60 s, ±25% jitter, capped at 120 s, never past
   `Pacing.deadline`). The retries come from a per-round budget: the entry's
   `retry_budget` (a whole number >= 0, validated at load time), else
   max(3, 25% of the round's prompts). A spent budget, or any other failure,
   fails the batch at once and aborts the other prompts. Each retry writes a
   `"phase": "retry"` row (prompt, try, backoff_s, budget_left), and
   `Pacing.retried` counts them. Before every acp-run spawn, `spawn_gate` runs
   `Pacing.stop`, a hook that may raise (skillopt-night ends the night on
   critical memory pressure). It then waits while the 1-minute load per core
   is above `Pacing.max_load` (off by default; skillopt-night uses 2.0),
   polling every `load_poll` s. A wait longer than `load_wait` (600 s) raises
   `StartupFailed` instead of spawning. The clock, sleep, load reading and
   randomness are `Pacing` fields, so tests never sleep and failover never
   imports skillopt-night.

9. **`perm`: deny or all** (2026-10-13). Operator decision, verbatim: "I want
   crush to be able to run any tools it wants. I want all of the TUIs and hermes
   to be able to run any tools they want." Scope: the SkillOpt-Sleep night
   (skillopt-night, `~/.skillopt-sleep/night.json`). A chain sets `"perm"` at the
   top level and an entry may override it; values are `deny` (the library
   default, unchanged for every other caller: acp-dispatch read-only reviews,
   `failover.py ask/check` without a perm, ...) and `all`; anything else is
   refused at load time, and `extra_args` can never pass `--perm` (item 6).
   Under `all`: acp-run gets `--perm all`; there is no canary (its job is to prove
   deny holds) and no exit-77 tripwire handling; preflight keeps the binary,
   secret, health URL, pool and probe checks; everything else in items 3-8 (the
   preflight cache, the load gate, startup retries, the empty temp dir per
   prompt, timeouts and the process-group kill) is the same. Every preflight,
   attempt and retry row in the attempt log carries `"perm"`, `check` prints a
   `perm` column, and the agy `--tripwire-exempt-kinds` flag is passed under
   `deny` only. A caller may also set `Entry.strip_user_config` (skillopt-night
   does, for every entry): `ask` then passes acp-run `--strip-user-config`, the
   2026-10-13 startup-failure fix (no user plugins, MCP servers or hooks for
   opencode, agy, crush and zcode) decoupled from deny; it is not a chain-file
   key and not in `EXTRA_ARGS_ALLOWED`.

   **The exposure, plainly:** with `perm: all` an unattended run gives agents
   full tool use with the user's permissions (shell, file edits anywhere the
   user can write, network) while the prompts carry mined session text, which
   can contain injected instructions. Each prompt still runs in an empty temp
   dir, so nothing is handed to it, but nothing confines it either. The `deny`
   default, its canary and its tripwire stay in force for every other caller.

## CLI

```sh
bin/failover.py registry                                   # the route table
bin/failover.py check --chain chain.json [--allow a,b]     # preflight table (exit 1 if nothing is ready)
bin/failover.py ask --chain chain.json -p 'question'       # first working entry answers
bin/failover.py run --chain chain.json -- mytool --model {model}   # first rc 0 wins
```

A chain file is a JSON list of entries, or `{"allow": [...], "perm":
"deny"|"all", "chain": [...]}` (`perm` default `deny`, item 9).
Entry keys: `tui` (required), `perm` (overrides the chain's), `model`, `effort`,
`floor_percent` (default 5),
`pool`/`pool_family` (override), `endpoint`, `secret`, `secret_env` (default
`OPENAI_API_KEY`, for `run`), `env`, `extra_args`, `timeout`, `label`,
`retry_budget` (startup retries per `ask_many` round; item 8).

Tests: `tests/test_failover.py` (through `~/ops/site-private/bin/bg uv run
pytest -q tests/test_failover.py`).
