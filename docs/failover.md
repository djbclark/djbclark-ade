# failover — one chain library for every tool that must not stop on one dead pool

`bin/failover.py` (2026-10-12) runs a task through an ordered chain of agent
routes and stops at the first that works. `bin/skillopt-night` is its first
consumer ([skillopt-sleep.md](skillopt-sleep.md) section 4). It is built so
`acp-dispatch`, bigteam and other bin tools can import it later.

## Pieces

1. **Registry** (`REGISTRY`): one `Tui` per route, with its kind (`acp` through
   acp-run, or `openai_compat`), acp agent id, vendor, aiuse pool and family
   (agy and opencode map the pool from the model prefix), known model ids, a
   model allow-regex (claude: Haiku or Sonnet only), the effort lever
   (`set:thought` for zcode, `suffix` for agy, none elsewhere), endpoint and
   secret name (SIPB).
2. **Policy at load time** (`load_chain`): the global `DENY` list (cursor,
   cline/ClinePass, hermes, opus, fable; operator 2026-10-12) is matched against
   tui, model and label; a caller allowlist; unknown TUIs; models a TUI refuses;
   efforts with no lever. A violation refuses the whole chain (`ChainError`).
3. **Preflight** (`preflight`): the agent has an `ok` row in `acp-run --list`
   (route_agent's reader), the pool is `usable_now` in `aiuse --available --json`
   with headroom above the entry's `floor_percent`, the secret is declared in
   sudo-secretspec (value-free `schema`), the endpoint accepts a TCP connection.
   Never calls a model.
4. **Ordered attempts** (`run_chain`): preflight, then the caller's function;
   `AttemptFailed` moves on. Every step is one line in the attempt log
   (`~/.local/state/failover/attempts.jsonl`, or the caller's path), ending in
   `chain_exhausted` when nothing worked.
5. **Executors**: `ask(entry, prompt)` answers one prompt in a fresh context
   (acp-run in an empty temp dir with `--perm deny`, prompt from a 0600 file,
   never argv; or an OpenAI-compatible POST with the key read into memory by
   `sudo-secretspec get`); `ask_many` answers a batch on one entry and fails the
   batch on the first failure; `run_command(entry, argv)` runs any command with
   `{tui} {agent} {model} {effort} {endpoint}` replaced in argv, `FAILOVER_*`
   exported, and the entry's secret exported only into that child.

## CLI

```sh
bin/failover.py registry                                   # the route table
bin/failover.py check --chain chain.json [--allow a,b]     # preflight table (exit 1 if nothing is ready)
bin/failover.py ask --chain chain.json -p 'question'       # first working entry answers
bin/failover.py run --chain chain.json -- mytool --model {model}   # first rc 0 wins
```

A chain file is a JSON list of entries, or `{"allow": [...], "chain": [...]}`.
Entry keys: `tui` (required), `model`, `effort`, `floor_percent` (default 5),
`pool`/`pool_family` (override), `endpoint`, `secret`, `secret_env` (default
`OPENAI_API_KEY`, for `run`), `env`, `extra_args`, `timeout`, `label`.

Tests: `tests/test_failover.py` (through `~/ops/site-private/bin/bg uv run
pytest -q tests/test_failover.py`).
