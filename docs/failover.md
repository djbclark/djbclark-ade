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
   for agy, none for opencode and crush), the native model id (claude `haiku`
   is `claude-haiku-5-5`), health URLs, probe, endpoint and secret name
   (the direct SIPB route).
2. **Policy at load time** (`load_chain`): the global `DENY` list (cursor,
   cline/ClinePass, hermes, opus, fable; operator 2026-10-12), plus any words the
   caller adds (skillopt-night adds muse, pi, grok, codex, copilot), is matched
   as whole tokens of tui, model and label (so `pi` never catches `api`); a caller allowlist; unknown TUIs; models a TUI refuses;
   efforts with no lever. A violation refuses the whole chain (`ChainError`).
3. **Preflight** (`preflight`): the agent has an `ok` row in `acp-run --list`
   (route_agent's reader), the pool is `usable_now` in `aiuse --available --json`
   with headroom above the entry's `floor_percent`, the secret is declared in
   sudo-secretspec (value-free `schema`), the endpoint accepts a TCP connection,
   a health URL (opencode's `sipb/` models: the proxy's `/api/version`) answers
   200. Routes with no quota pool to read (crush) get a one-prompt probe, the
   only preflight step that calls a model; `check --probe` runs it, plain
   `check` reports it as not run.
4. **Ordered attempts** (`run_chain`): preflight, then the caller's function;
   `AttemptFailed` moves on. Every step is one line in the attempt log
   (`~/.local/state/failover/attempts.jsonl`, or the caller's path), ending in
   `chain_exhausted` when nothing worked.
5. **Executors**: `ask(entry, prompt)` answers one prompt in a fresh context
   (acp-run in an empty temp dir with `--perm deny`, prompt from a 0600 file,
   never argv; acp-run's `claude -p` fallback also reads stdin since
   2026-10-12). Tools stay off because acp-run enforces deny per agent and its
   tripwire exits 77 when a tool still runs without asking, which `ask` turns
   into `AttemptFailed`; the canary checks it before use. Or an
   OpenAI-compatible POST with the key read once per process by
   `sudo-secretspec get`, sent only to the registry endpoint, https or
   loopback, and never across a redirect; `ask_many` answers a batch on one entry and fails the
   batch on the first failure; `run_command(entry, argv)` runs any command with
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

   **Accepted risk (agy only):** an unasked read can pull a file's contents into
   an answer, and answers flow into reflection and into staged skill edits.
   `skillopt-night preadopt-check` flags commands, URLs and secret words but not
   leaked file content, so adoption review must read the diff for such content.

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
