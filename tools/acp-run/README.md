# acp-run

Run one prompt through a coding agent over the
[Agent Client Protocol](https://agentclientprotocol.com) (ACP), headless, and get
the agent's final message on stdout. It is how one agent on this machine hands a
self-contained task to another vendor's agent: Claude Code, Codex,
opencode, Cursor, Hermes and OMP. (the xAI CLI, Copilot, Qwen Code, Devin, Cline,
Antigravity (`agy`), zcode, Pi, Crush, goose and kiro had adapters until the 2026-11-06/07 slim-down retired them; the
lessons are in `docs/tui-lessons-learned.md`.) Vendor, model, effort and
context for each agent are in the 2026-10-15 section below.

A single-file [uv script](https://docs.astral.sh/uv/guides/scripts/) on the
official Python SDK (`agent-client-protocol`); no daemon, no state beyond its
logs. MIT licensed. The SDK is pinned below 1.0 until 1.0 is tested.

```sh
acp-run --list                                  # agents and the command each runs
acp-run claude --info                           # modes, config options, auth methods
acp-run codex -C ~/src/repo --add-dir ~/.local/state/bigteam/task -p 'Reply with exactly: OK' --model gpt-6-astra
acp-run claude -C ~/src/repo -f brief.md --perm deny --timeout 1200 > report.md
acp-run codex -C ~/src/repo --interactive --inbox /tmp/codex-in   # a session you keep prompting
```

## What it adds over a bare ACP client

1. **A per-agent table**: the launch command for each agent, per-agent default
   config options (`DEFAULT_SET`), each agent's own auto-approve mode (`YOLO_SET`),
   and environment set-up where an agent needs it.
2. **A permission policy** answering every `session/request_permission`.
   acp-run runs yolo for every agent (operator 2026-10-14): there are three
   policies, `all`, `read-only` (2026-10-19) and `deny`. `read-only`: the agent
   may read and change nothing. Its read-only tools (ACP kinds `read`, `search`,
   `fetch`) run without a permission request and are answered yes if they ask;
   any other tool trips the tripwire (exit 77) and any other request is refused,
   except an `execute` request whose command line passes `readonly_command` (an
   allow-list: cat, ls, rg, git log/show/diff, a plain `curl` GET, joined by `|` `&&` `;`;
   it runs outside codex's sandbox, so the list refuses `#`, program paths outside
   `/usr/bin` `/bin` `/opt/homebrew/bin`, long options that run a program (prefixes
   included, `--` is no stop), unquoted globs, braces, `~` and backslashes, and `git` unless the request's cwd finds an
   ordinary repository whose config (`git config --list`, env-injected keys included) names no diff/textconv/
   filter/fsmonitor/gpg helper that is a relative path or inside the repo; a `curl` GET can carry read data in its URL, as WebFetch can). When codex's
   only refusal option is `cancel` (it ends the turn), acp-run continues the same session up to 3 times (the exit check judges the last turn's words, not an earlier turn's "I will look next"; the summary line says `refusal_end=1` when the final turn ended on a refusal).
   claude gets a session whose built-in tools are only Read, Grep, Glob, LS,
   WebFetch and WebSearch (`_meta.claudeCode.options.tools`; no user settings, no
   MCP servers, mode `default`); codex the `read-only` mode (its sandbox runs shell commands
   unasked, so an unasked `execute` does not trip there, 2026-10-19); opencode a
   `permission` block (`OPENCODE_CONFIG_CONTENT`) allowing read, glob, grep, list,
   webfetch, websearch and denying the rest. Every other agent is
   refused with exit 2 and a one-line reason (no equivalent mode verified);
   `acp-run <agent> --info` lists the `perm_modes` an agent supports. `deny` gives
   claude no tools at all, so it is for a text-only answer, never a review that
   has to read. The old `scoped:P1,P2` and `ask` are still
   accepted for old callers but are not enforced: each prints one line,
   `acp-run: warning: --perm <value> is no longer enforced: acp-run runs yolo
   for every agent (treated as --perm all); use --perm read-only for a read-only
   run`, and the run is exactly `--perm all` (`ask` no longer needs
   `--interactive`).
   - `all` (default): allow everything, including under `--interactive`.
   - `deny`: refuse everything, and make the agent actually ask (2026-10-12,
     after an adversary review found four agents ran tools without ever asking):
     claude-agent-acp gets a session with no built-in tools, no user settings
     (so no `bypassPermissions` default or allow rules), no MCP servers and no
     bypass (`_meta.claudeCode.options`), then mode `default`;
     opencode gets `OPENCODE_CONFIG_CONTENT={"permission":"deny"}`. (zcode, agy and crush had their own
     deny machinery here until they retired, 2026-11-06.)
     A tripwire backs this up: any non-think tool call that starts or completes
     without a permission request cancels the turn and exits 77. The `claude -p`
     fallback runs with `--tools ""`, `--strict-mcp-config`, `--disallowedTools '*'`
     and `--setting-sources project` (no user hooks), and always reads its prompt
     from stdin. `--tripwire-exempt-kinds read,search` lets tool calls of those
     read-only ACP kinds run unasked without tripping (any other kind is a usage error). Options are never abbreviated (`allow_abbrev=False`): `--per all`
     is an error, not `--perm all`.
     Since 2026-10-13 a `deny` run that is not `--interactive` also starts
     **opencode without the user's plugins, MCP servers and hooks**
     (claude already ran that way). On the 2026-10-13 SkillOpt-Sleep
     night all 21 failed attempts died while the agent started: opencode's
     "Location plugins did not finish activating". It has no switch for it, so it gets
     a per-run 0700 temp config, removed after the run; the user's own files are
     only read, never changed:
     - opencode (v2.0.27): `OPENCODE_CONFIG_DIR=<tmp>` replaces
       `~/.config/opencode` as its global config directory, so the plugin dirs
       there (`plugins/rtk.ts`, ...) are never scanned. `<tmp>/opencode.json`
       holds only `$schema`, `provider`, `model`, `small_model`,
       `enabled_providers`, `disabled_providers` and `experimental.max_retries`
       from the user's `opencode.json`/`opencode.jsonc` (and `OPENCODE_CONFIG`,
       which is then unset): no `mcp`, `plugin`, `agent`, `command`, hooks.
       `OPENCODE_DISABLE_PROJECT_CONFIG=1` (and `OPENCODE_CONFIG_PROJECT_DISABLE=1`)
       skips project `.opencode/` dirs and `opencode.json` files. Logins
       (`opencode-go/`) live in opencode's data dir and still work. Not stripped:
       skills in `~/.claude/skills` and `~/.agents/skills` (opencode reads them
       with no switch to turn it off) and any `.well-known` remote config.
     The log gets a `user_config` record naming what was stripped (server, plugin
     and key names only, never values) and the result record `user_config:
     "stripped"`. `--keep-user-config` or `ACP_RUN_KEEP_USER_CONFIG=1` keeps the
     user's config (logged as `"action": "kept"`); if the temp config cannot be
     built, or an opencode config file cannot be read or parsed (JSONC with
     comments and trailing commas is fine), the run keeps it too and says so on
     stderr, naming the file. `--perm all` and `--interactive` runs are
     unchanged unless `--strip-user-config` is given.
     `--strip-user-config` (env `ACP_RUN_STRIP_USER_CONFIG=1`, 2026-10-13) applies
     the same strip under any non-interactive `--perm` for opencode. It is a startup-reliability switch, not a permission control: the
     SkillOpt-Sleep night runs `--perm all --strip-user-config` (operator,
     2026-10-13). Outside deny nothing permission-related is added: opencode gets
     no `OPENCODE_CONFIG_CONTENT`.
     Temp dirs are `acp-run-<agent>-strip-<pid>-*` and are swept like deny dirs.
     Under `--perm deny` the flag adds nothing; `--keep-user-config` wins.
     Hardening after the adversary review (2026-10-13): config layers are
     deep-merged as opencode does; a literal secret in a provider block (an
     `apiKey`-, `token`-, `secret`-like key or any `headers` value) goes to the
     child as `ACP_RUN_OPENCODE_SECRET_<n>` and appears in the file only as
     `{env:...}` (values that are not printable ASCII, or contain a quote,
     backslash or brace, stay in the 0600 file and are listed in
     `secrets_in_file`); relative `{file:x}` references are made absolute. This
     is **not secret-free**: the env var reaches every child process the agent
     starts (LSP servers, formatters, crash dumps). What it buys is that nothing
     secret is left on disk after a SIGKILL. The temp dir is built after the
     signal handlers are in place and removed before the cancel/kill waits
     (opencode), so
     SIGTERM and early errors leave nothing behind. It is not removed right after `session/new`: opencode
     watches its config dir and reloads on change. Dirs are named `acp-run-<agent>-deny-<pid>-*`, and every deny run
     first sweeps this user's such dirs under the temp base that are older than
     3 hours, belong to a dead pid (1-7 digits; anything else is never swept),
     and are real dirs (never symlinks): that covers runs killed with SIGKILL.
     A failing sweep only prints a warning; it never stops the run.
3. **`--add-dir DIR` (repeatable)**: add extra workspace roots sent as
   `additionalDirectories` in `session/new`. If advertised in `initialize` (in
   `agentCapabilities` or `sessionCapabilities`), it is sent directly; if
   unadvertised, it is still sent, falling back with a one-line log to a retry
   without it if rejected. Lets an agent whose file tools are confined to its
   workspace roots read and write outside `-C` (such as `acp-dispatch` report
   folders).
4. **`--model`, `--mode`, `--effort LEVEL`, `--context SIZE` and `--set ID=VALUE`**
   for any config option `--info` lists. Since 2026-10-15, `--effort` and
   `--context` are the normalized names (`256k`, `500k`, `1m`, and the other
   sizes that agent's section lists). Order: provider, model, other `--set`
   and mode, then effort, then context. A value the agent or the chosen model
   cannot take is a usage error (exit 2) before any prompt, and it lists the
   valid values. Stderr, before the summary
   line: `acp-run: applied: model=... effort=... ctx=...` (also on the JSONL
   `result` record as `applied`, a separate `applied` record, and `--json`).
   Unreadable values are `(unverified)`. A requested value the agent reports
   differently is failure class `config`, exit 1. On cursor,
   `--set reasoning_effort=LEVEL` hits only option id `reasoning_effort`
   (`grok-4.7`, `claude-sonnet-5-5`, `claude-haiku-5-5`, ...). Use `--effort` on the other cursor models.
   `--info --model M [--effort] [--context] [--set]` applies that combination
   with no prompt. `--info --all-models` is the per-model option matrix.
   The per-agent section below is the table.
5. **An audit trail**: every ACP event is logged as JSONL (default
   `~/.local/state/acp-run/`), ending with a `result` record (summary and exit
   code), and one summary line goes to stderr: stop reason, seconds, tool calls,
   permissions allowed/denied, tokens, cost, failure class, log path.
6. **Timeouts that cancel the turn** (`session/cancel`), and a bounded handshake
   with retries (`--handshake-tries`), falling back to `claude -p` for the
   `claude` agent when its ACP session never starts (`--no-fallback` to disable).
   The fallback runs as a known conversation (`claude -p --session-id`: the
   `--session-id UUID` you pass, else a fresh one) and logs it as `new_session`,
   so a later `--resume` reaches exactly that conversation. Over ACP,
   claude-agent-acp chooses the id and gives it to Claude as `--session-id`, so
   the logged `new_session` id is already Claude's own.
   `--handshake-timeout` (env `ACP_RUN_HANDSHAKE_TIMEOUT`) bounds `initialize`
   and `session/new` each: 40 s by default, 90 s for `claude`, whose
   `session/new` takes 13 s on an idle machine and 17-24 s under heavy load.
   Each handshake try starts a fresh agent after a timeout, or after a
   `transient` ACP error in `initialize` or `session/new` (backoff 1, 2, 4..
   10 s; nothing has run yet, so a retry repeats nothing). Added 2026-10-13
   after opencode's `ServiceUnavailableError` ("Location plugins did not finish
   activating") failed 24 `session/new` calls in one night with no retry. Quota,
   plan, auth and unclassified errors are not retried. The timeout error names
   the step that hung (`initialize hung`, `session/new hung`).
   A prompt that finishes on the same tick as a 1 s poll times out is taken as
   finished. Before 2026-10-13 it was reported as a timeout (exit 124), which
   threw away two good answers.
   `--wrapup-grace S` (off by default; `acp-dispatch` passes 300) sends one more
   prompt after the timeout cancel (`--wrapup TEXT`, default "time is up, write
   your final report now") and waits up to S seconds, so a slice cut off in a
   hung command still writes its report; the run still exits 124 and the summary
   says `wrapup=<stop reason|timeout|skipped|error>`. Added 2026-10-10 after an
   opencode slice with verified work lost its report to a `git commit` whose
   pre-commit Gradle hook queued on the machine-wide Gradle slot.
   `--timeout 0` removes the turn deadline and disables the wrap-up turn;
   handshake limits still apply. While waiting, acp-run checks `<log>.extend`
   at intervals of at most 30 seconds. Write a nonnegative whole number of
   seconds there to add to the current deadline, or `0` to remove it. Positive
   extensions leave an unlimited turn unlimited. The file is consumed and
   deleted; malformed input is logged and ignored. `deadline_extended` records
   carry the old and new monotonic deadlines (`null` means unlimited). A costly
Go advisory turn (`--go-advisory`, see the OpenCode Go section) never extends:
acp-run deletes the file, logs `deadline_extension_refused` and keeps the deadline
fixed at start + `--timeout` (at most 600 s), so a hand-edited control file cannot
bypass it either.
7. **Safe permission answers**: only an offered `allow_once` or `reject_once`
   option is ever selected. Never an `*_always` option, which an agent may save
   beyond this run (Hermes writes `allow_always` to a permanent allowlist), and
   never `cancelled`, which cancels the whole turn. An allow with no
   `allow_once` offered becomes a `reject_once`; with neither offered the agent
   gets a JSON-RPC error. A tool call with no kind gets one inferred from its
   title (`Edit ...` is an edit, as acpx does), logged as `inferred_kind` in the
   permission record.
8. **Delivery checks.** Agents report some provider failures as a normal answer
   (`end_turn`). acp-run fails such a turn (exit 1, a `FAILED <class>` line on
   stderr, `"failure"` in `--json`) when the whole short reply is a refusal
   (`Upgrade your plan to continue`), when it is the model declining the task
   (`Sorry, I cannot fulfill your request ...`: class `refused`, never retried, and
   acp-dispatch records it as NO-REPORT), or when the reply ends in a provider or
   transport error line (`Error: RetriableError: [unavailable] PING timed out`),
   reported as "reply truncated; edits may be present". ACP errors are classified
   the same way: `quota`, `plan`, `auth` or `transient`. The patterns are a short
   table at the top of the script (`FAILURE_CLASSES`, `REPLY_REFUSALS`,
   `MODEL_REFUSALS`, `TAIL_ERROR`).
9. **Opt-in prompt retry** (`--prompt-retries N`, default 0): a prompt that fails
   with a transient error before any tool call or permission request is retried
   with backoff (1, 2, 4 s, at most 10 s). Quota, plan and auth failures are not
   retried.
10. **Opt-in machine-load guard** (`--max-load L`, env `ACP_RUN_MAX_LOAD`): refuse
   to start (exit 75) while the 1-minute load average per CPU core is above `L`;
   `--load-wait SECS` (env `ACP_RUN_LOAD_WAIT`) waits up to that long for the
   load to drop first. Off by default.
11. **Clean interrupts**: SIGINT/SIGTERM send `session/cancel`, stop the agent
    and exit 130/143, so a killed run does not leave the agent running.
12. **An interactive mode** (`--interactive`, below): one ACP session that stays
    open for more prompts, from a terminal, a pipe or a drop directory.
13. **Verify-and-retry (`--verify CMD`)**: an opt-in verify loop for models that end
    their turn early (`end_turn`) before finishing work. Runs `CMD` as a shell command
    with `-C DIR` as cwd (exit 0 = pass). If `CMD` fails, acp-run sends a follow-up
    prompt into the same session with the exit code and truncated output (last 40
    lines, max 3000 chars), instructing the agent to fix the problem and retry.
    Retries up to `--verify-retries N` times (default 2), with `--verify-timeout SECS`
    (default 180) per check run. Respects the overall `--timeout` deadline.
    The run summary (stderr line, `--json`, and JSONL log `result` record) records
    `verify=pass|fail` and `verify_attempts=<n>`. A final failed verification prints
    a warning on stderr and preserves exit 0 (off by default; callers decide).

    ```sh
    acp-run opencode -C dir -p '...' --verify 'python3 -m unittest' --verify-retries 2
    ```

## Per-agent choices: vendor, model, effort, context (2026-10-15)

Landed 2026-10-15 (6528ccf, 77bd2bf, 0221561, faead67, ada7620). Value lists are from that agent's `--info` on this Mac that day. Regenerate: `acp-run <agent> --info --all-models` (per-model option matrix, no prompt). One combination, no prompt: `acp-run <agent> --info --model M [--effort L] [--context S] [--set ID=VALUE]`.

1. `--effort`: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`, `default`. Aliases, not clamps: `extra-high`=`xhigh`, `off`=`none`. `--context`: `200k`, `256k`, `272k`, `400k`, `500k`, `1m`, or a positive integer (`k`=1000, `m`=1,000,000).
2. Order, every agent: provider, model, other `--set` and mode, effort, context. A model switch resets effort and context and changes which values exist.
3. A LEVEL or SIZE the agent or model cannot take exits 2 before any prompt and names the valid values.
4. Read-back, stderr before the summary line: `acp-run: applied: model=... effort=... ctx=...`. Same fields on the JSONL `result` record (`applied`), a separate `applied` record, and `--json`. Unreadable values are marked `(unverified)` (`effort=high(unverified)`). A requested value the agent reports differently is failure class `config`, exit 1 (option response before the prompt, or `usage_update.size` after the turn). Under `--interactive` the line is still printed; a post-turn window mismatch does not change the exit code.
5. `--meta JSON` deep-merges into `session/new` `_meta` over `systemPrompt` and the deny meta. `--agent-arg ARG` (repeatable) appends to the launch command. `--agent-env K=V` (repeatable; one argument may be `K=V,K2=V2`, split only before another `NAME=`) appends to the child environment. Per host, `~/.config/acp-run.env` or `$ACP_RUN_ENV_FILE`: `ACP_RUN_ARGS_<AGENT>` (shell-split), `ACP_RUN_ENV_<AGENT>="K=V,K=V"`.
6. `HERDR_PANE_ID`, `HERDR_ENV`, `HERDR_WORKSPACE_ID` and `HERDR_TAB_ID` (the last two since 2026-10-25, when the Codex tool environment began to pass the herdr ids on), `PASEO_AGENT_ID`, `PASEO_AGENT_CWD` and `ORCA_TERMINAL_HANDLE` and `ADE_OPENCODE_SESSION_ID` and `ADE_OPENCODE_DIRECTORY` are removed on every run, and `ACP_RUN_AGENT=1` is set (2026-10-20: `bin/self-slash` refuses lifecycle actions when it sees the marker; a slice that kept `PASEO_AGENT_ID` could `/clear` or archive the caller's Paseo agent). (`ACP_RUN` itself is taken: it holds the acp-run path for `session-finder`.)
7. acp-run's `--effort` and `--context` are first-class (`acp-run <agent> --info --model M --effort E --context C` checks them). acp-dispatch stopped passing them on 2026-11-06 (it launches through Paseo: `--effort` becomes `paseo run --thinking`).
8. No `--fast`. Use `--set fast=on|off` (claude Opus only), `--set fast=true|false` (cursor), `--set fast-mode=on|off` (codex), or a model id (`grok-4.7-build-fast`, copilot `claude-opus-4.8-fast`). Thinking budget: `--agent-env MAX_THINKING_TOKENS=N` or `ACP_RUN_ENV_CLAUDE`. Not implemented (exit 2, or not a flag): hermes shadow home for effort/context, crush `/set_reasoning_effort`, opencode/qwen context caps (`OPENCODE_CONFIG_CONTENT` `limit.context` untested; a cap cannot raise a window), agy `--auth-method` (`AGY_ACP_DEFAULT_MODEL` via `ACP_RUN_ENV_AGY`), `ZCODE_ACP_QUOTA_AUTO_RESUME=0` (operator's choice). Claude `--context 1m` does not add `[1m]`.

(The `ocx-*` grok ids, OpenAI models via the opencodex proxy on `127.0.0.1:10100`, went with the proxy on 2026-10-19.) Cursor `--set reasoning_effort=LEVEL` hits only option id `reasoning_effort`: `grok-4.7`, `claude-sonnet-5-5`, `claude-haiku-5-5`, `gemini-4-argon`, `gemini-3.8-flash`. Other cursor models use option `effort` or `reasoning`; use `--effort`.

`pick_config` tries every option of a category and ignores a trailing `(openai)` or `[1m]` (`--model qwen3.8-max` selects `qwen3.8-max(openai)`). An ambiguous short name exits 2 (hermes `claude-sonnet-5.5`). `--info` without `--model` is the default model's options only. hermes and crush `--info` include `session/new`'s `models`.

### claude

https://code.claude.com/docs/en/model-config — claude-agent-acp 0.90.0, Claude Code 2.1.300.

Provider is inherited env only (`ANTHROPIC_BASE_URL`, `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`). No `--provider`. Until 2026-10-19 this Mac's `HTTPS_PROXY` was the opencodex intercept `127.0.0.1:10200`, which added GPT rows (descriptions starting `opencodex`) to claude's model list; the proxy is uninstalled and the list is Anthropic-only again.

`--model` (unique-token match): `default`/`opus` = Opus 5.5, `fable` = Fable 5.1, `sonnet` = Sonnet 5.5, `haiku` = Haiku 5.5, `claude-sonnet-5`, `claude-opus-5`, `claude-fable-5`, `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`. TUI also `best`, `opusplan`, full ids, `[1m]`.

Effort option `effort`: `low` `medium` `high` `xhigh` `max`, plus `default`. No `xhigh` on Opus 4.6 or Sonnet 4.6. No option on Haiku 4.5 and older. Defaults: `high`; Opus/Sonnet/Haiku 5.5 `medium`; Opus 4.7 `xhigh`. `ultracode` is a setting, not a level. Also `CLAUDE_CODE_EFFORT_LEVEL`, settings `effortLevel` / `modelSettings` (`max` refused there), `ultrathink`.

Context: Fable 5.1, Fable 5, Sonnet 5, Sonnet 5.5, Haiku 5.5, Opus 4.7+ are 1M native. Opus 4.6 and Sonnet 4.6 are 200K, 1M only via `[1m]` (plan dependent) — `--context 1m` does not add that suffix. `--context 200k` sets child `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` (haiku `usage_update.size` 1000000 to 200000). `--context 1m` leaves the model's own window. Other sizes exit 2. A 1m request that comes back 200k is `FAILED config`. Auto-compact 100K–1M: `--autocompact`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`. Gateway: `CLAUDE_CODE_MAX_CONTEXT_TOKENS`.

Fast option `fast` `on`/`off` only on `opus`, `claude-opus-5`, `claude-opus-4-8`. Not on fable, sonnet, haiku, Opus 4.7, Opus 4.6. Extended thinking is always on for 5.5 and Fable.

### codex

https://developers.openai.com/codex/config-reference , openai/codex#53742, #53336 — codex-acp 2.2.2 (@openai/codex 0.160.1), cli 0.162.1.

Env `MODEL_PROVIDER`, `CODEX_API_KEY`, `OPENAI_API_KEY`, or `--oss --local-provider lmstudio`/`ollama`. This Mac: ChatGPT Plus. No `--provider`.

Models: `gpt-6.1-sol`, `gpt-6-astra`, `gpt-6-sol`, `gpt-6-luna` (user default), `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`. Hidden: `gpt-reserve`, `codex-auto-review`.

Effort option `reasoning_effort`. `low medium high xhigh max ultra` on gpt-6.1-sol, gpt-6-astra, gpt-6-sol, gpt-5.6-sol, gpt-5.6-terra. No `ultra` on gpt-6-luna, gpt-5.6-luna. Defaults: 6.1-sol, 6-astra, 5.6-sol `low`; the rest `medium`. CLI docs also list `minimal`. TUI: `-c model_reasoning_effort`, `/model`.

Context is fixed by the model: gpt-6.1-sol 500000 (475000 effective); every other visible model 272000 (258400); all have `max_context_window` 872000 and `effective_context_window_percent` 95. `--context 500k` only with `--model gpt-6.1-sol`; `--context 272k` only on the others; anything else exits 2 (the message names `--model gpt-6.1-sol`). Does not change the model. The launch-time `CODEX_CONFIG` (`model_context_window`, merged with any `CODEX_CONFIG` already in the env, `ACP_RUN_ENV_CODEX` or `--agent-env`; a value that is not a JSON object exits 2) is how the size is set; on codex 0.162.1 / codex-acp 2.2.2 (400000 reads 380000, 200000 reads 190000, gpt-6.1-sol 800000 reads 760000) the path works. Read-back after the turn: `usage_update.size` must be SIZE × 95% (rounded, 1 token slack), else failure class `config`, exit 1; the `applied:` line shows `ctx=400k/380000` (requested/effective).

Fast: `--set fast-mode=on` or `off` (all 7). `service_tier` `fast` (priority) / `flex` / default. Priority copy: 6.1-sol and 6-astra "2x speed, increased usage"; 6-sol and 6-luna "1.5x speed"; 5.6 "1.5x speed, increased usage". `features.fast_mode`.


### opencode

https://opencode.ai/docs/models/ , https://opencode.ai/v2/docs/models , https://models.dev/api.json — 2.0.29.

Connected: alibaba 58, alibaba-cn 90, opencode (Zen) 44, opencode-go 31, sipb 19 (242 ids, same as `opencode models`). Provider is the slash prefix. Examples: `opencode/claude-opus-5-5`, `opencode/claude-sonnet-5-5`, `opencode/claude-fable-5-1`, `opencode/gpt-6-sol`, `opencode/gpt-6.1-sol`, `opencode/gpt-5.5`, `opencode-go/glm-5.3`, `opencode-go/kimi-k3`, `opencode-go/deepseek-v4-pro`, `opencode-go/qwen3.8-max`, `sipb/qwen3.6:35b-a3b-q4_K_M`. No user `model`: `opencode-go/gemini-4-argon-contributor`. Dashes, not dots. TUI `/models`, `opencode run -m provider/model[#variant]`. Effort is re-read after a second model set (the first response can still be the previous model's list).

Effort option `effort`; `default` = no variant, always offered. Groups plus `default`, 2026-10-15. `none,low,medium,high,xhigh,max`: opencode/claude-opus-5-5, gpt-6-astra, gpt-6-sol, gpt-6.1-sol, opencode-go/deepseek-v4-pro, gpt-6-luna, grok-4.6. `low,medium,high,xhigh,max`: opencode/claude-fable-5-1, claude-sonnet-5, claude-sonnet-5-5, claude-haiku-4-5, gpt-6-luna (Zen), grok-4.7, deepseek-v4-pro (Zen), opencode-go/claude-haiku-5-5. `none,low,medium,high,xhigh`: gpt-5.5, gpt-5.5-pro, gpt-5.4-nano, gpt-5.3-codex-spark. `low,medium,high,xhigh`: gpt-5.4-mini, grok-build-0.1, opencode-go/grok-4.7, hy3. `medium,high,xhigh`: gpt-5.6-terra. `minimal,low,medium,high,xhigh`: muse-spark-1.3-contributor-free, nemotron-3-ultra-free, opencode-go/qwen3.7-plus. `minimal,low,medium,high`: gemini-3.8-flash. `low,medium,high`: opencode/gemini-4-argon, glm-5.3, gemini-3.5-flash-lite, opencode-go/glm-5.2, cat-jam-free, every `sipb/*`. `low,high,max`: kimi-k3, gemini-3.1-pro, gpt-5.3-codex, deepseek-v4.1-flash (Zen), opencode-go/gemini-4-argon-contributor. Also `none,high,max` / `high,max` / `max` / `none,thinking` / `none,low,medium,xhigh` / `none,low,high,max` / `none,low,high` on Alibaba, Qwen, Longcat, Muse, Space-Bunny, Kimi-code, Hy4. No effort option on 97 Alibaba/Qwen/DeepSeek-R1 ids. No fast switch (`#variant` is effort).

Context exits 2. `limit.context`: opencode/claude-opus-5-5 1000000; gpt-6-sol 1050000 (`input` 922000); opencode-go/glm-5.2 1000000; kimi-k3 1048576; most Qwen/Alibaba 131072–262144. Missing limit treated as 200000 (`sipb`; servers run ~32K). `compaction.*`.

### cursor

https://cursor.com/docs/models/grok-4-7 , https://cursor.com/docs/cli/reference/parameters , https://cursor.com/docs/cli/acp — cursor-agent 2026.10.14-0f9edde. No prompt sent.

`--model` is the plain id. Rejected: presets (`grok-4.7-high-fast`) and brackets (`claude-opus-4-8[context=1m,effort=high,fast=false]`). `default` = Auto. Vendors covered below: Claude Fable 5.1/5, Opus 5.5/5/4.8/4.7/4.6/4.5, Sonnet 5.5/5/4.6/4.5/4, Haiku 5.5/4.5; GPT-5.6 Sol/Terra/Luna, 5.5, 5.4, 5.4 mini/nano, 5.3 Codex, 5.2, 5.1, 5 mini; Gemini 4 Argon, 3.8/3.7/3.6/3.5/3 Flash, 3.1 Pro, 2.5 Flash; Grok 4.7/4.6/4.5; Composer 2.5; Muse Spark 1.3; Kimi K3, K2.7 Code; GLM 5.2, 5.3, 5.3 Flash.

`--effort`: category `thought_level`, never id `thinking`. `xhigh` = `extra-high`. `--context`: option `context`, or exit 2 if the model has none. Grok 4.7 input above 256k is 2×; Fast is 3×. Fast is the Premium default. `--set fast=true|false`, `--set thinking=true|false` only where listed.

1. Grok 4.7: context `256k`/`500k`; [reasoning_effort] default `high` of `low`/`medium`/`high`/`xhigh`; fast `false`/`true`.
2. Grok 4.6: [effort] `low`/`medium`/`high` (default)/`xhigh`; fast. Grok 4.5: [effort] `low`/`medium`/`high` (default); fast default `true`. Composer 2.5: fast only, default `true`.
3. Opus 5.5: context `300k`/`1m`; [effort] default `medium` of `low`/`medium`/`high`/`xhigh`/`max`; fast. Opus 5 and 4.8: thinking; context `300k`/`1m`; [effort] default `high`, low through max; fast. Opus 4.7: same, effort default `xhigh`. Opus 4.6: thinking; context `200k`/`1m`; [effort] `low`/`medium`/`high`/`max` (no `xhigh`); no fast. Opus 4.5: thinking only.
4. Fable 5.1 and 5: thinking; context `300k`/`1m`; [effort] low through max, default high; no fast. Sonnet 5.5: context `300k`/`1m`; [reasoning_effort] low through max, default high. Sonnet 5: thinking, context, [effort]. Sonnet 4.6: thinking; context `200k`/`1m`; [effort] `low`/`medium`/`high`/`max`. Sonnet 4.5: thinking. Sonnet 4: thinking default `false`. Haiku 5.5: thinking; context `300k`/`1m`; [reasoning_effort] low through max. Haiku 4.5: thinking.
5. GPT-5.6 Sol/Terra/Luna: context `272k`/`1m`; [reasoning] default `medium` of `none`/`low`/`medium`/`high`/`xhigh`/`max`; fast. GPT-5.5 and 5.4: context `272k`/`1m`; [reasoning] `none`/`low`/`medium`/`high`/`extra-high`; fast. GPT-5.4 mini/nano: [reasoning] `none`/`low`/`medium`/`high`/`xhigh`. GPT-5.3 Codex: [reasoning] `low`/`medium`/`high`/`extra-high` (default `extra-high`); fast. GPT-5.2: [reasoning] low through `extra-high`; fast. GPT-5.1: `low`/`medium`/`high`. GPT-5 mini: none.
6. Gemini 4 Argon and 3.8 Flash: [reasoning_effort] `low`/`medium`/`high`. 3.7 Flash: [effort] `low`/`medium`/`high`. 3.6 Flash: [effort] `minimal`/`low`/`medium`/`high`. 3.1 Pro, 3 Flash, 3.5 Flash, 2.5 Flash: none.
7. Muse Spark 1.3: context `300k`/`1m`; [effort] `minimal`/`low`/`medium`/`high` (default)/`xhigh`/`max`. Kimi K3: [reasoning] `low`/`high`/`max` (default max). K2.7 Code: none. GLM 5.2: `high`/`max`. GLM 5.3 and 5.3 Flash: `low`/`high`/`max`.



### hermes

`~/.hermes/hermes-agent/website/docs/user-guide/features/acp.md` — 0.21.5. No provider prompt.

`config_options` null. `--model` is `session/set_model` on `session/new` `models` (436; `have:` shows 40 then "... N more"). Read-back `(unverified)`. `--set` is stored and ignored. Shape `provider:model` or `custom:name:model`. Counts: nous 64, openrouter 61, anthropic 13, openai-codex 13, copilot 30, copilot-acp 31, xai-oauth 14, alibaba 15, alibaba-cn 15, alibaba-coding-plan 10, opencode-zen 88, opencode-free 5, custom 77 (`custom:sipb-llms:*`). `model.provider` here `cline2`. Examples: `nous:anthropic/claude-fable-5.1`, `nous:openai/gpt-6-astra`, `nous:openai/gpt-6.1-sol`, `openai-codex:gpt-6.1-sol`, `anthropic:claude-opus-5`, `xai-oauth:grok-4.7`, `alibaba-coding-plan:qwen3.7-plus`, `opencode-zen:big-pickle`, `custom:sipb-llms:deepseek-r1:32b`. `claude-sonnet-5.5` is ambiguous and refused; `nous:anthropic/claude-sonnet-5.5` is not. Audit current: `custom:big-pickle`. Not persisted. `hermes --provider` is oneshot/tui only.

`--effort` exits 2. `config.yaml`: `agent.reasoning_effort` (`medium` here), `agent.reasoning_overrides`. Levels `none minimal low medium high xhigh max ultra`. Provider wire clamps: Codex GPT-6 Astra low through max (`ultra` dropped), Kimi K3 `low`/`high`/`max`, Grok 4.6+ through `xhigh`. TUI `--reasoning`, `/reasoning`. No `HERMES_HOME` shadow.

`--context` exits 2. Bigger window = model id `openai-codex:gpt-6-astra-900k`, `openai-codex:gpt-6-sol-900k`. Resolve: `model.context_length`, `providers.<p>.models.<m>.context_length`, `~/.hermes/context_length_cache.yaml`, endpoint, models.dev, else 128K. Cache: gpt-5.5 codex 272000, nous 1050000. `compression.threshold` 0.4, `threshold_tokens` 100000. `-pro` `-fast` `-flex` `-900k` are ids (`gpt-6-astra-pro` and the same suffixes).



### omp

`omp acp` (omp 18.12.2, added to the table 2026-10-19 when the per-run gate was lifted: its Claude
API credits are a normal tier). The session has no `model` config option, so `--model M` becomes
the root flag (`omp --model M acp`, M like `anthropic/claude-sonnet-5-5`); `--effort` drives its
`thinking` option, which lists low..max once a Claude model is set. Every prompt run (`--resume` included) needs
`--model anthropic/<claude model>`, else it exits 2: omp's configured default is `github-copilot/gpt-5.6-luna` and
would spend the Copilot reserve, and `github-copilot/claude-...` is a Copilot model. A pass-through `--agent-arg`
naming `--model`, `--models`, `--smol`, `--slow`, `--plan`, `--prewalk-into`, `--plan-yolo-into`, `--provider`,
`--profile`, `--api-key` or `--config` (or an abbreviation) exits 2 too: it would replace the admitted model after
the guard (2026-11-03). `--info` is exempt; `ACP_RUN_OMP_ANY_MODEL=1` overrides all of it.
Needs an enabled Anthropic login in omp
(`omp login`); with an expired one the run ends `No API key found for anthropic` (2026-10-19).



## Dispatch slice controls (2026-10-11; acp-dispatch left acp-run 2026-11-06)

`bin/acp-dispatch` no longer runs acp-run: since 2026-11-06 it is a `paseo run` shim (its docstring has the flags,
the `--perm` boundaries and the exit codes; `--perm read-only`/`deny` for Claude go through `bin/review-launch`). Its
resume, reroute and extend subcommands, the automatic quota resume with its pmset wake and sudoers rule, `--effort`/
`--context` probing through `acp-run --info`, `--acp-arg` and the final-message recovery are gone. `tell` and `outcome`
stay (inbox plus `paseo send`; the fields `route_agent.py calibrate` reads).

What stays here is acp-run's own side of the 2026-10-19 lesson. Under `--perm deny` claude gets a session with no
built-in tools at all, so a reading review printed its tool calls as text and ended in seconds (two frontier slices
lost). acp-run fails a turn that made no tool call and replied with pseudo tool-call markup (`<invoke name=`,
`<function_calls>`, a fenced `tool_call` or `json` block holding a tool and its arguments, `print(default_api.`) as
`FAILED fake-tool-calls`, exit 1, with a line naming `--perm read-only`. XML markup quoted in a code block, or in a run
that made real tool calls, passes. `--perm deny` is for a run that must not touch anything and needs no tools.

## Interactive mode

`acp-run <agent> --interactive` (`-i`) keeps the ACP connection, which is the
session, open and reads prompt after prompt in one process. The one-shot contract
is unchanged without it: stdout is the final message, stderr one summary line.

```sh
acp-run claude -C ~/src/repo -i                              # type at the prompt
acp-run claude -C ~/src/repo -i -p 'Read AGENTS.md first.'   # first prompt from -p/-f
acp-run codex -C ~/src/repo -i --inbox /tmp/codex-in         # also take files dropped there
acp-run claude -C ~/src/repo -i --resume SESSION_ID          # reopen an earlier session
```

1. **Output.** Agent text streams to stdout as it arrives; each tool call is one
   `⚙ <title>` line and a failed one a `✗` line. Thoughts show only with
   `--show-thinking`. After each turn it prints the stop reason, seconds and tool
   count, then waits for the next prompt.
2. **Prompt sources**, whichever comes first. A line on stdin is one prompt. A
   `*.txt` or `*.md` file dropped into `--inbox DIR` (polled every second, taken in
   name order, deleted once read) is one prompt, whole file. The first prompt
   comes from `-p` or `-f`; without either it starts at the prompt. A prompt that
   arrives during a turn queues as the next one. `--timeout` applies to each turn.
3. **Commands.** `/exit` (or EOF) ends the session; typed at the terminal during
   a turn it cancels that turn first, while from a pipe or the inbox it waits
   behind the prompts already queued. `/cancel` cancels the running turn
   (`session/cancel`) and returns to the prompt.
4. **Ctrl-C** cancels the running turn, or exits when idle. The agent runs in its
   own process group, so the terminal's interrupt does not hit it directly.
   SIGHUP exits 129.
5. **Delivery checks per turn.** Each turn gets the checks above; a failed one
   prints `FAILED <class>` and returns to the prompt rather than ending the
   session. On exit the stderr summary carries `turns=N` (or `--json` the last
   turn's text), and the exit code is the last turn's (0 when no turn ran).
6. **Permissions.** Requests are answered by the `--perm` policy without
   asking: `all` (the default) allows each one, `deny` refuses each one. The
   interactive `--perm ask` y/n prompt was removed on 2026-10-14 (operator:
   acp-run runs yolo for every agent); `--perm ask` now warns and runs as
   `all`.
7. **`--resume ID`** reopens an ACP session with `session/load` (history is
   replayed to the log only, not printed) or `session/resume`, whichever the agent
   advertises in `initialize` (`--info` shows `loadSession` and
   `sessionCapabilities`). It exits 2 if the agent advertises neither.
   Since 2026-10-18 (ACP session-resume RFD): with both advertised it calls
   `session/resume` first (no replay, "0 messages") and falls back to
   `session/load` only on a -32601/-32602 error (logged as
   `resume_fallback_load`). `--add-dir` is sent again, in full, on whichever call
   runs, but only when the agent advertises
   `sessionCapabilities.additionalDirectories`; otherwise one stderr line says the
   extra directories were not sent. An unknown id (resource-not-found) or a replay
   from a different session id exits 2 before any prompt. At the end of every
   run (after the last `--interactive` turn) it sends `session/close` when the
   agent advertises `sessionCapabilities.close`, before stopping the agent
   (5 s, errors only logged as `close_session_failed`).
8. **herdr reports.** In a herdr pane (`HERDR_PANE_ID` set; `HERDR_BIN_PATH` or
   `herdr` on `PATH`) it reports `working` and `idle` as source `acp-run`
   (`blocked`, for a pending `--perm ask` question, went with it on 2026-10-14), with a resume command
   (`acp-run <agent> -C DIR --interactive --resume ID ...`), and releases the
   pane on exit. Reports run in the background and never hold up the session.
   herdr before 0.9.2 rejects the resume command, so on 0.9.1 it is dropped.
   The agent process is started without `HERDR_PANE_ID` and `HERDR_ENV`, so its
   own herdr hooks (Claude Code's report as `herdr:claude`) do not compete for
   the pane.
9. **Sending a prompt from outside.** On herdr 0.9.1 `herdr agent prompt <pane>
   TEXT` cannot reach an acp-run session, so a caller uses the inbox (write a
   `.txt` file into `--inbox DIR`; write to a temporary name and rename it, so a
   half-written file is not picked up) or `herdr pane run <pane> TEXT`, which
   sends a line to the pane's terminal, where acp-run reads it from stdin.
10. **The log gets a `turn` record per turn** (`n`, `stop_reason`, `seconds`,
    `exit`, and `failure`, `error` or `warning` when set), written before the
    final `result` record, which carries `turns`. A one-shot run writes one `turn`
    record too.

## Git identity guard (2026-10-26)

ACP's reference-transaction hook keeps agent commits under the operator's identity,
without replacing fixture identities in temporary repositories. Its configuration
travels through `GIT_CONFIG_PARAMETERS`, so Codex's default KEY/SECRET/TOKEN
environment-name exclusions remain enabled without stripping `GIT_CONFIG_KEY_n`
out of a counted tuple. No Codex policy change is needed.

Before launching, acp-run converts complete inherited `GIT_CONFIG_COUNT` tuples
using Git's single-quoted format. Configuration order stays: inherited counted
entries, ACP's guard entries, then existing `GIT_CONFIG_PARAMETERS` text. Nested
launches normalize inherited tuples too, without adding the guard twice. An invalid
count or a missing key/value refuses the launch with exit 2 and a variable-name-only
diagnostic; the incomplete tuple is never cleared as a fallback. An empty
`GIT_CONFIG_COUNT` is zero, the way Git reads it (`env && *env` in `config.c`), so a
launcher that exports it empty still launches. A counted key that embeds
a credential refuses too, by index only, never by value: the name-based exclusion used
to keep such a token out of an agent's tool environment, and the quoted transport would hand
it over. It refuses in two ways.

By URL position: every URL-scoped family counts, not just `url.*` — git resolves
`http.<url>.*` and `credential.<url>.*` for the matching URL as well (`git config
--get-urlmatch http.sslVerify https://user:token@host/x` answers the setting configured
under that subsection, and answers nothing for another host) — so every `://` in the key
must be followed by an authority without `@`, whatever the section (`url.`, `HTTP.`) or
scheme (`HTTPS://`) case, and past any run of slashes (`https:///user:token@host` sends
that userinfo although its authority is empty), and username-only userinfo refuses with it
(`url.ssh://git@github.com/.insteadOf`), because a username cannot be told apart from a
token without decoding it. A `?` or `#` after a `://` refuses too: a query or a fragment is
a credential position git matches exactly, with no `@` needed — with
`http.https://example.org/repo?access_token=TOK3N.sslVerify` configured,
`git config --get-urlmatch http.sslVerify 'https://example.org/repo?access_token=TOK3N'`
answers `true` while the same URL without the query answers nothing, and a loopback
`git ls-remote` sent the token in its request target (2026-10-30). A query is legitimate in a
real remote (`https://dev.azure.com/o/p/_git/r?path=/src`, a cgit web url `?h=main`), so such a
key refuses too: that is the intended trade, and it stays usable in `~/.gitconfig`. The one
exception is an `includeIf.hasconfig:` glob pattern with a `?` wildcard, which cannot travel
through a counted config. A `credential.` subsection that is
a PARTIAL url with no scheme is the one form git resolves as well — measured with
`git credential fill`, a helper under `credential.example.org.helper` runs for
`url=https://example.org/x`, and one under `credential.<userinfo>@example.org.helper` runs
for `url=https://<userinfo>@example.org/x` — so such a subsection refuses whenever its
authority carries `@` at all, or a `?`/`#`: no colon is required, because a GitHub PAT is
used as a username and git url-decodes `%3A`, so `credential.user%3Atoken@host.helper`
matches a request whose username is literally `user:token`.

By token shape: a name matching a known token pattern (`ghp_`, `github_pat_`, `glpat-`,
`xox?-`, `sk-`, `hf_`, `npm_`, `pypi-`, `AIza`, `AKIA`/`ASIA`, an `eyJ` JWT header, each
with a length floor) refuses wherever it appears in the key, in a subsection
(`remote.<token>.url`) and in a URL path alike — the name filter hid the token whether or
not git resolves the key, so the exposure is the NAME, not the setting's meaning. Three
limits keep that off ordinary names: a match never starts mid-word, each prefix is matched
in the case its issuer uses, and each floor sits just under the real token length, measured
per issuer (`ghp_` 36, `github_pat_` 82, `glpat-` 20, `hf_` 34, `npm_` 36, and LiteLLM's
default generated `sk-` + 22). Refusing a name that merely resembles a prefix
(`remote.sk-learn-upstream-fork.url`, `remote.ghp_mirror01.url`,
`remote.pypi-mirror-internal-eu.url`) would break a launch for nothing, and an earlier head
refused exactly those (adversary round 10, 2026-10-30). A non-default shorter LiteLLM key
and a name glued straight onto a token with no separator (`remote.xghp_…url`) are the
documented limits, as is a name whose `sk-` body is long enough to reach the floor. Only
KEYS are checked: a credential in a counted VALUE (`GIT_CONFIG_VALUE_n`) never went through
the name filter, so refusing one would be a different change. A secret of an unknown shape
sitting in a path segment cannot be told apart from path data
(`url.https://example.org/@scope/.insteadOf` must travel), so it still travels: that is
this check's documented limit.

Both of those checks also run on every **percent-decoded** spelling of the key, not only the
text as written, because the exposure is the name and not the setting's meaning: an agent
reads the converted key and can decode it. Measured with `git config --get-urlmatch
http.sslVerify <url>` on git 2.56.0, a setting written under
`http.https://host/ghp%5Fabc....sslVerify` answers for both `https://host/ghp_abc...` and
`https://host/ghp%5Fabc...`, so git treats the spellings as one subsection too (codex
security review, 2026-10-30). Decoding repeats until the text stops changing — each step
strictly shortens, so it terminates — which covers a double encoding (`ghp%255F...`);
escapes that are not valid escapes are left alone, so a `%` in ordinary path data travels.
The cost is a key that only spells a credential once decoded, such as
`credential.user%40host.helper` or `url.https%3A%2F%2Fuser%3Atoken%40host/x.insteadOf`:
that refuses too, which is the intended trade, and both stay usable in `~/.gitconfig`.

A port has no `@`, so `credential.https://host:8443.helper`, the plain
`credential.example.org.helper`, an ordinary `remote.origin.url` and a name that only
resembles a prefix (`remote.sk-1.url`) still travel. Use a credential helper or
`~/.gitconfig` for the rest. The workspace Git guard recognizes only the exact ACP
hook event and expected guard path in this environment transport, while retaining
compatibility with older counted launches.

## Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | `end_turn` with some output |
| 1 | another stop reason, an agent error, an empty reply (no text and no tool calls; or no text under `--perm deny` or `read-only`, or after a denied permission), or a delivery-check failure (quota, plan, auth, provider error, truncated reply, or `FAILED fake-tool-calls`: no tool ran and the reply is tool calls printed as text) |
| 2 | usage error, or invalid/incomplete counted Git environment configuration (before agent launch) |
| 5 | empty reply and every permission request was denied (the code acpx uses) |
| 75 | refused to start by `--max-load` |
| 127 | the agent binary is not on `PATH` after `ACP_RUN_BIN_WAIT` seconds (default 90, `0` disables, at most 600, junk means the default; an upgrade may be relinking it, 2026-10-20). The binary is the program the launch command runs: for crush, `crush-acp` behind its `env NAME=VAL` wrapper, never `env` (2026-10-23); `--list` marks it `--` the same way |
| 77 | under `--perm deny` or `read-only` a tool ran without a permission request (tripwire; the turn is cancelled) |
| 124 | timed out (`session/cancel` sent first, then the agent is killed) |
| 130, 143 | interrupted by SIGINT, SIGTERM (with `--interactive` also 129 on SIGHUP; Ctrl-C cancels a running turn instead of exiting) |

A reply with text exits 0 even when every permission was denied (a `--perm
deny` review can still deliver its report); the summary line then carries a
`warning=`.

Run `acp-run --help` for every flag.

## Install

Needs [uv](https://docs.astral.sh/uv/) and the agents' own CLIs/adapters.

The script itself is self-contained (a `uv run --script` header pulls its
dependencies): a copy on your PATH runs every agent and every non-Go model
with no other file. On this machine it lives in djbclark-ade
at `tools/acp-run/acp-run`
and is reached as `~/.local/bin/acp-run` → `~/ops/site-private/bin/acp-run` →
`~/ops/site-djbclark/tools/acp-run` → here. Elsewhere, copy the script onto
your PATH:

```sh
install -m 755 tools/acp-run/acp-run ~/.local/bin/acp-run
acp-run --list
```

**OpenCode Go models need the Go policy bundle** (added 2026-10-25; guard added
2026-10-25). The policy stays in one place, `bin/go_model_policy.py` +
`config/go-model-policy.json`, and the context guard in one place,
`opencode-plugins/go-context/`. acp-run loads them only when a requested or
applied model is `opencode-go/…`, from exactly two roots and never from
`sys.path`, the cwd, the script's own directory or the user's OpenCode config:
(1) the checkout the script runs from (`tools/acp-run/acp-run` with `../../bin`,
`../../config` and `../../opencode-plugins`: running or symlinking it in place
just works), else (2) the installed bundle `~/.local/share/acp-run/go-policy/`:

```text
~/.local/share/acp-run/go-policy/bin/go_model_policy.py
~/.local/share/acp-run/go-policy/config/go-model-policy.json
~/.local/share/acp-run/go-policy/opencode-plugins/go-context/index.js
~/.local/share/acp-run/go-policy/opencode-plugins/go-context/package.json
```

```sh
d=~/.local/share/acp-run/go-policy
install -d "$d/bin" "$d/config" "$d/opencode-plugins/go-context"
install -m 644 bin/go_model_policy.py "$d/bin/"
install -m 644 config/go-model-policy.json "$d/config/"
install -m 644 opencode-plugins/go-context/index.js opencode-plugins/go-context/package.json "$d/opencode-plugins/go-context/"
```

Re-run those lines whenever the classification or the guard changes (the copy is
a snapshot). To track the checkout instead, make `bin`, `config` and
`opencode-plugins` in `$d` symlinks to the checkout's directories: the guard reads
`<its real dir>/../../config/go-model-policy.json`, and acp-run refuses a Go launch
whose guard would read a different policy file than the helper enforces.

Why the guard is part of the bundle: a Go launch with `--perm read-only` or
deny, or with `--strip-user-config`, replaces OpenCode's global config with a
per-run 0700 directory (no user plugins, MCP, project config; see above). That
directory gets exactly one plugin, `plugins/ade-go-context`, a symlink to the
trusted guard of the root above, so the cost guard survives sanitizing while every
other plugin stays excluded (a user plugin of the same name is not copied). If the
guard is absent, incomplete or paired with another policy file, the Go launch is
refused (exit 2 before any agent starts; exit 1 if it is only noticed later),
never run unguarded. Non-Go launches never read the guard. A Go launch that is not
sanitized (`--perm all` without `--strip-user-config`, `--interactive`,
`--keep-user-config`) runs on the user's own OpenCode config, where the guard is
whatever the user linked (`opencode-plugins/go-context/README.md`).

Without the bundle, non-Go prompts run as before, and a Go prompt is refused
before any agent starts (exit 2 at launch, exit 1 if the applied model turns out
to be Go), with a message naming the paths tried. A missing, unparsable or invalid
policy never falls back to a permissive default. If a checkout helper exists but
cannot load its policy, the run is refused rather than falling back to an installed
snapshot.

The agent table reflects the machine it was written on; edit `AGENTS`, `DEFAULT_SET` and
`YOLO_SET` at the top of the script for yours. (The `agy` notes, the clientInfo gate, the server comparison and the
Crush data dir section went with those agents, 2026-11-06; the repo history has them.)

## Why not acpx?

[acpx](https://github.com/openclaw/acpx) is the maintained general-purpose ACP CLI
and is the better choice for most people. On 2026-10-05 it lacked two things this
script exists for: permission rules scoped to file paths (since dropped:
acp-run runs yolo, with only `deny` as a gate, operator 2026-10-14), and per-agent
environment and default config options. If acpx gains those, a thin wrapper over
it would replace this script.

Several of the ideas above come from acpx (MIT): exit code 5, prompt retries on
transient errors, tool-kind inference from titles, cooperative interrupts.

### OpenCode Go bounded advice (2026-10-25)

OpenCode prompt runs require `--model provider/model`; an unqualified or omitted
model could resolve to Go without a cost check. Before prompting, the applied
model must exactly match that qualified ID, with verified read-back; fuzzy
aliases and unverified resumed selection are refused. Routine models are listed in
`config/go-model-policy.json` (a standalone copy needs the bundle, see Install). Costly Go models require `--go-advisory --perm
read-only --timeout 600` (a positive timeout no greater than 600). They refuse
interactive mode, prompt retries and `--verify`; wrap-up grace is disabled.
Go model selection through `--set model=...` is refused. Unknown Go models fail
closed until classified. This does not restrict other providers' models.
`acp-dispatch` supplies the flag only for an explicit bounded advisory role.
See [context hygiene](../../docs/context-hygiene.md) for native V2 compaction.

Identity-guard corrections (2026-10-30): the hook command shell-quotes its path. Nested launches verify
the inherited hook configuration and reinstall missing pairs instead of trusting the email marker alone.
Credential-bearing counted keys remain refused for every agent: converting them to PARAMETERS would
make them readable to agents that filter KEY names, so this conservative transport rule is shared.

On 2026-10-31 (PR 175), the identity-hook exemption began requiring the exact expected guard path
and its canonical shell quoting. A path containing shell syntax followed by `/../` cannot gain an
exemption through lexical path normalization.
